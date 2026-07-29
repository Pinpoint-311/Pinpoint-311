/**
 * Apple MapKit JS provider registration.
 *
 * Reached only through registry.ts's dynamic import, so a town on any other
 * provider downloads none of this and makes no request to apple-mapkit.com.
 *
 * Configuration read from MapProviderConfig:
 *
 *   options.mapkitToken      A MapKit JS JWT (ES256, signed by the backend with
 *                            the town's MapKit private key, `iss` = Team ID,
 *                            `kid` = key id, `origin` = the town's Pinpoint
 *                            origin). Simple, but the map stops working when
 *                            the token expires — fine for kiosks, not for staff
 *                            sessions that stay open all day.
 *   options.mapkitTokenUrl   Preferred. A backend endpoint returning a fresh
 *                            JWT as `{"token": "..."}` or as the bare string.
 *                            MapKit re-invokes its authorization callback near
 *                            expiry, so this keeps long sessions alive.
 *                            Requested with credentials, so it may sit behind
 *                            the normal session cookie.
 *   apiKey                   Accepted as a fallback carrier for the JWT so a
 *                            deployment that only has the generic key field can
 *                            still be configured, but it is NOT an API key —
 *                            MapKit has no such thing.
 *   options.mapkitVersion    CDN version segment. Default '5.x.x'.
 *   options.mapkitScriptUrl  Full script URL override.
 *   options.language         BCP-47 language for labels and geocoding.
 *   options.geocodeCountries string[] of ISO-3166-1 alpha-2 codes.
 *
 *   styleId is ignored: MapKit JS has no custom style or style-id concept.
 *
 * What a town gives up by choosing this provider: the spatial-bias heatmap
 * (capabilities.canvasOverlay is false), the 'terrain' base map, control
 * placement, and map tilt. See APPLE_CAPABILITIES for why in each case.
 */

import {
    GeocodingProvider,
    MapInitOptions,
    MapProviderConfig,
    MapProviderFactory,
    MapRenderer,
} from '../../types';
import { createAppleGeocoder } from './geocoder';
import { loadAppleMapKit } from './loader';
import { APPLE_CAPABILITIES, AppleMapRenderer } from './renderer';

function str(options: Record<string, unknown> | undefined, key: string): string | undefined {
    const value = options?.[key];
    return typeof value === 'string' && value ? value : undefined;
}

function strList(options: Record<string, unknown> | undefined, key: string): string[] | undefined {
    const value = options?.[key];
    if (!Array.isArray(value)) return undefined;
    const list = value.filter((v): v is string => typeof v === 'string');
    return list.length ? list : undefined;
}

export const appleMapProvider: MapProviderFactory = {
    id: 'apple',
    displayName: 'Apple Maps (MapKit JS)',
    capabilities: APPLE_CAPABILITIES,

    load(config: MapProviderConfig): Promise<void> {
        const token = str(config.options, 'mapkitToken') ?? config.apiKey ?? null;
        const tokenUrl = str(config.options, 'mapkitTokenUrl') ?? null;
        if (!token && !tokenUrl) {
            return Promise.reject(new Error(
                'Apple MapKit requires a signed JWT: set options.mapkitTokenUrl (preferred) or options.mapkitToken',
            ));
        }

        return loadAppleMapKit({
            token,
            tokenUrl,
            version: str(config.options, 'mapkitVersion'),
            scriptUrl: str(config.options, 'mapkitScriptUrl'),
            language: str(config.options, 'language'),
        }).then(() => undefined);
    },

    createRenderer(container: HTMLElement, _config: MapProviderConfig, options: MapInitOptions): MapRenderer {
        return new AppleMapRenderer(container, options);
    },

    createGeocoder(config: MapProviderConfig): GeocodingProvider {
        return createAppleGeocoder({
            language: str(config.options, 'language'),
            countryCodes: strList(config.options, 'geocodeCountries') ?? ['US'],
        });
    },
};
