/**
 * Public entry point for the map abstraction. Components import from here and
 * never from src/maps/providers/* — reaching into an adapter directly would
 * re-hardwire the vendor and defeat the point.
 */

export * from './types';
export * from './geo';
export * from './popup';
export { createMap, createGeocoder, chainGeocoders, loadMapProvider, availableMapProviders, isMapProviderId } from './registry';
export { resolveMapProviderConfig, legacyMapProviderConfig, DEFAULT_MAP_PROVIDER } from './config';
export { backendGeocodingProvider } from './providers/backend';
export {
    assetIcon,
    requestIcon,
    clusterIcon,
    clusterStyle,
    puckIcon,
    locationPinIcon,
    safeColor,
} from './markerIcons';
