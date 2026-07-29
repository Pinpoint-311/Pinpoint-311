/**
 * MapLibre GL provider registration.
 *
 * Reached only through registry.ts's dynamic import, and maplibre-gl itself is
 * reached only through sdk.ts's dynamic import inside `load()` — so a Google
 * town downloads neither this module nor the SDK.
 */

import {
    GeocodingProvider,
    MapInitOptions,
    MapProviderConfig,
    MapProviderFactory,
    MapRenderer,
} from '../../types';
import { PhotonGeocoderOptions, createMapLibreGeocoder } from './geocoder';
import { MAPLIBRE_CAPABILITIES, MapLibreRenderer } from './renderer';
import { loadMapLibre } from './sdk';
import { readProviderOptions } from './styles';

export const maplibreMapProvider: MapProviderFactory = {
    id: 'maplibre',
    displayName: 'MapLibre GL',
    capabilities: MAPLIBRE_CAPABILITIES,

    // No API key: the default styles are free, key-less sources. A town that
    // configures commercial tiles puts the key in its own style URL.
    load(_config: MapProviderConfig): Promise<void> {
        return loadMapLibre();
    },

    createRenderer(container: HTMLElement, config: MapProviderConfig, options: MapInitOptions): MapRenderer {
        return new MapLibreRenderer(container, readProviderOptions(config.options), options);
    },

    createGeocoder(config: MapProviderConfig): GeocodingProvider {
        return createMapLibreGeocoder(config.options as PhotonGeocoderOptions | undefined);
    },
};
