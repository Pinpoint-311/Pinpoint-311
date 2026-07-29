/**
 * Azure Maps provider registration.
 *
 * Reached only through registry.ts's dynamic import, and azure-maps-control is
 * reached only through sdk.ts's dynamic import inside `load()`.
 */

import {
    GeocodingProvider,
    MapInitOptions,
    MapProviderConfig,
    MapProviderFactory,
    MapRenderer,
} from '../../types';
import { AzureGeocoderOptions, createAzureGeocoder } from './geocoder';
import { AZURE_CAPABILITIES, AzureMapRenderer, AzureProviderOptions } from './renderer';
import { loadAzureMaps } from './sdk';

export const azureMapProvider: MapProviderFactory = {
    id: 'azure',
    displayName: 'Azure Maps',
    capabilities: AZURE_CAPABILITIES,

    load(config: MapProviderConfig): Promise<void> {
        if (!config.apiKey) return Promise.reject(new Error('Azure Maps subscription key is required'));
        return loadAzureMaps();
    },

    createRenderer(container: HTMLElement, config: MapProviderConfig, options: MapInitOptions): MapRenderer {
        if (!config.apiKey) throw new Error('Azure Maps subscription key is required');
        return new AzureMapRenderer(
            container,
            config.apiKey,
            (config.options ?? {}) as AzureProviderOptions,
            options,
        );
    },

    createGeocoder(config: MapProviderConfig): GeocodingProvider {
        if (!config.apiKey) throw new Error('Azure Maps subscription key is required');
        return createAzureGeocoder(config.apiKey, config.options as AzureGeocoderOptions | undefined);
    },
};
