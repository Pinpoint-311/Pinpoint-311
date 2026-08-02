/**
 * Runtime provider selection.
 *
 * Adapters are reached through dynamic import() so Vite emits one chunk per
 * provider: a town configured for Esri must never download Google's adapter
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
    esri: async () => (await import('./providers/esri')).esriMapProvider,
    apple: async () => (await import('./providers/apple')).appleMapProvider,
    azure: async () => (await import('./providers/azure')).azureMapProvider,
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
    const suggesters = chain.filter(p => p.suggest);

    return {
        id: chain.map(p => p.id).join('+') || 'none',
        reverseGeocode: position => attempt(p => p.reverseGeocode(position), null),
        geocode: query => attempt(async p => {
            const results = await p.geocode(query);
            return results.length ? results : null;
        }, []),

        // Suggestions fall back the same way geocoding always has.
        //
        // This used to pick the first provider with a `suggest` and call it
        // directly -- no chain, no catch. So the address box was the only part
        // of the geocoding layer that could not degrade: `geocode` and
        // `reverseGeocode` were served by the backend and kept working, while
        // one blocked browser API left the autocomplete dead and threw into a
        // render. "Everything else resolves addresses fine" and "the address
        // box does nothing" were both true at once, which is a confusing thing
        // to be told.
        suggest: suggesters.length
            ? async (query, options) => {
                for (const provider of suggesters) {
                    try {
                        const results = await provider.suggest!(query, options);
                        if (results.length) return results;
                    } catch (error) {
                        console.warn(`Suggest provider "${provider.id}" failed, falling back:`, error);
                    }
                }
                return [];
            }
            : undefined,

        // Resolution has to ask the provider that issued the suggestion; ids
        // are provider-opaque and one provider cannot read another's.
        resolveSuggestion: suggesters.some(p => p.resolveSuggestion)
            ? async suggestion => {
                for (const provider of suggesters) {
                    if (!provider.resolveSuggestion) continue;
                    try {
                        const result = await provider.resolveSuggestion(suggestion);
                        if (result) return result;
                    } catch {
                        // Wrong provider for this id, or it is unavailable.
                    }
                }
                return null;
            }
            : undefined,

        // A widget that cannot attach returns null rather than throwing, which
        // is what the interface already promises callers -- they fall back to
        // suggest() and their own list. Before this, a provider whose SDK was
        // present but whose API was not enabled threw out of the attach call.
        attachAutocomplete: widgetProvider
            ? (input, options) => {
                try {
                    return widgetProvider.attachAutocomplete!(input, options);
                } catch (error) {
                    console.warn(
                        `Autocomplete widget "${widgetProvider.id}" could not attach; ` +
                        `falling back to suggestions:`, error);
                    return null;
                }
            }
            : undefined,
    };
}
