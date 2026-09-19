/**
 * Esri / ArcGIS provider registration.
 *
 * Reached only through registry.ts's dynamic import, so a town on any other
 * provider downloads none of this and makes no request to js.arcgis.com.
 *
 * Configuration read from MapProviderConfig:
 *
 *   apiKey            ArcGIS Location Platform API key. Required only for
 *                     Esri-hosted basemaps and the World Geocoding service.
 *                     A town serving its own basemap and locator from its own
 *                     ArcGIS Server can leave it null.
 *   styleId           The basemap. Accepts an Esri well-known basemap id
 *                     ('streets-navigation-vector'), a 32-hex portal item id,
 *                     or the URL of a MapServer / ImageServer / VectorTileServer.
 *                     Null falls back to Esri's street basemap.
 *   options.arcgisVersion        SDK version on the CDN. Default '4.31'.
 *   options.arcgisScriptUrl      Full SDK URL, for an internally mirrored build.
 *   options.arcgisCssUrl         Theme stylesheet URL (e.g. the dark theme).
 *   options.trustedServers       string[] — on-prem ArcGIS Server origins that
 *                                may receive tokens.
 *   options.corsEnabledServers   string[] — older on-prem servers needing an
 *                                explicit CORS allowance.
 *   options.locatorUrl           Locator base URL. Defaults to Esri's World
 *                                GeocodeServer. Point this at the county's own
 *                                composite locator. This is the name the
 *                                backend puts in `map_credentials` (from the
 *                                ARCGIS_LOCATOR_URL secret), so it is the one
 *                                that actually arrives.
 *   options.geocodeServiceUrl    Accepted as an alias for the above, for a
 *                                caller that builds its own config.
 *   options.geocodeToken         Token for that locator, if it differs from
 *                                apiKey. Defaults to apiKey.
 *   options.geocodeCountries     string[] of ISO-3166-1 alpha-2 codes.
 *   options.geocodeCategory      Esri category filter for suggest().
 */

import {
    GeocodingProvider,
    MapInitOptions,
    MapProviderConfig,
    MapProviderFactory,
    MapRenderer,
} from '../../types';
import { createEsriGeocoder } from './geocoder';
import { loadEsri } from './loader';
import { ESRI_CAPABILITIES, EsriMapRenderer } from './renderer';

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

export const esriMapProvider: MapProviderFactory = {
    id: 'esri',
    displayName: 'Esri / ArcGIS',
    capabilities: ESRI_CAPABILITIES,

    load(config: MapProviderConfig): Promise<void> {
        // No API key check: an entirely self-hosted ArcGIS Server deployment
        // needs no key, and rejecting here would lock out exactly the towns this
        // adapter exists for.
        return loadEsri({
            version: str(config.options, 'arcgisVersion'),
            scriptUrl: str(config.options, 'arcgisScriptUrl'),
            cssUrl: str(config.options, 'arcgisCssUrl'),
            apiKey: config.apiKey ?? null,
            trustedServers: strList(config.options, 'trustedServers'),
            corsEnabledServers: strList(config.options, 'corsEnabledServers'),
        }).then(() => undefined);
    },

    createRenderer(container: HTMLElement, _config: MapProviderConfig, options: MapInitOptions): MapRenderer {
        return new EsriMapRenderer(container, options);
    },

    createGeocoder(config: MapProviderConfig): GeocodingProvider {
        return createEsriGeocoder({
            // `locatorUrl` is what the backend emits, and reading only the
            // alias meant the browser silently ignored a town's own locator and
            // asked Esri's world service instead -- while geocode_dispatch.py
            // honoured the same setting server-side. So the county address
            // locator, the single biggest local accuracy win this adapter
            // exists for, reached everything *except* the address box residents
            // type into.
            serviceUrl:
                str(config.options, 'locatorUrl') ?? str(config.options, 'geocodeServiceUrl'),
            token: str(config.options, 'geocodeToken') ?? config.apiKey ?? null,
            countryCodes: strList(config.options, 'geocodeCountries') ?? ['USA'],
            category: str(config.options, 'geocodeCategory') ?? null,
        });
    },
};
