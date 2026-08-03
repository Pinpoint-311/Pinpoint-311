/**
 * Turn the town's saved GIS settings into a MapProviderConfig.
 *
 * This is the seam the whole provider abstraction hangs from, and until now
 * nothing called it. Every map component built its config with
 * `legacyMapProviderConfig(apiKey)` instead, which hardcodes
 * `provider: DEFAULT_MAP_PROVIDER` -- so a town could select Esri, Azure or
 * Apple in the admin console, have its credentials accepted and its Test button
 * go green, and still get Google. Or, because the pages gated the map on a
 * *Google* key being present, get no map at all and no error explaining why.
 *
 * The backend has sent everything needed for a while: `map_provider`,
 * `map_credentials` (only the fields that provider actually uses) and
 * `map_provider_missing`. The older Google-shaped fields are still emitted
 * alongside them and are still read here, so a payload from a backend that
 * predates the change keeps working.
 */

import { isMapProviderId } from './registry';
import { MapProviderConfig, MapProviderId } from './types';

export const DEFAULT_MAP_PROVIDER: MapProviderId = 'google';

export interface RawMapsConfig {
    map_provider?: string | null;
    geocode_provider?: string | null;
    /**
     * Neutral credential names for whichever provider is selected: `apiKey`,
     * `styleId`, and per-provider extras like `locatorUrl` (Esri) or `token`
     * (Apple, minted server-side because its signing key must not reach a
     * browser).
     */
    map_credentials?: Record<string, unknown> | null;
    /** Non-empty means the town picked a provider it has not finished setting up. */
    map_provider_missing?: string[] | null;

    /** Legacy, still emitted. Only ever applied when the provider is Google. */
    google_maps_api_key?: string | null;
    google_maps_map_id?: string | null;
    map_api_key?: string | null;
    map_style_id?: string | null;
}

function str(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value : null;
}

export function resolveMapProviderConfig(raw: RawMapsConfig | null | undefined): MapProviderConfig {
    const provider = isMapProviderId(raw?.map_provider)
        ? (raw!.map_provider as MapProviderId)
        : DEFAULT_MAP_PROVIDER;

    const creds = (raw?.map_credentials ?? {}) as Record<string, unknown>;

    // The Google-shaped fields are a fallback *only* for Google. Handing a
    // Google key to the Esri adapter would turn "this town is misconfigured"
    // into a confusing authentication error from a vendor they never chose --
    // and the backend deliberately does not return one provider's secret when
    // another is selected, so falling back across providers would also mean
    // inventing a credential that was not sent.
    const legacyKey = provider === DEFAULT_MAP_PROVIDER ? str(raw?.google_maps_api_key) : null;
    const legacyStyle = provider === DEFAULT_MAP_PROVIDER ? str(raw?.google_maps_map_id) : null;

    // Everything the provider sent, minus the two lifted to named fields, so an
    // adapter can read its own extras (Esri's locator, Apple's token) without
    // this function needing to know each provider's vocabulary.
    const options: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(creds)) {
        if (k === 'apiKey' || k === 'styleId' || v === null || v === undefined) continue;
        options[k] = v;
    }
    // Apple's adapter looks for `mapkitToken`; the backend calls it `token`
    // because that is what it is on the wire for every provider that mints one.
    const token = str(creds.token);
    if (token && !options.mapkitToken) options.mapkitToken = token;

    return {
        provider,
        apiKey: str(creds.apiKey) ?? str(raw?.map_api_key) ?? legacyKey,
        styleId: str(creds.styleId) ?? str(raw?.map_style_id) ?? legacyStyle,
        ...(Object.keys(options).length ? { options } : {}),
    };
}

/**
 * Whether the town's chosen map can actually be drawn.
 *
 * The pages used to ask "is there a Google API key?", which is the same question
 * only for Google towns and is the reason an Esri town saw an empty panel where
 * its map should be. The backend already works out what is missing for the
 * selected provider -- including Apple, whose token it mints and can therefore
 * report on -- so this defers to that and only falls back to "is there a key"
 * for a payload that predates the field.
 */
export function mapProviderReady(raw: RawMapsConfig | null | undefined): boolean {
    if (!raw) return false;
    if (Array.isArray(raw.map_provider_missing)) return raw.map_provider_missing.length === 0;
    return !!resolveMapProviderConfig(raw).apiKey;
}

/**
 * Whether a resolved config carries any credential at all.
 *
 * Not simply `!!config.apiKey`: Apple authenticates with a short-lived signed
 * token rather than a static key, so a correctly configured Apple town has no
 * `apiKey` and would otherwise be told its map is unconfigured.
 */
export function hasMapCredential(config: MapProviderConfig): boolean {
    return !!(config.apiKey || (config.options && config.options.mapkitToken));
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
