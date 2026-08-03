import { describe, it, expect } from 'vitest';

import { hasMapCredential, mapProviderReady, resolveMapProviderConfig } from './config';

/**
 * A town could select Esri, have its API key accepted, watch the Test button go
 * green, and get no map at all.
 *
 * Four adapters, a provider catalogue, per-provider credential fields and a live
 * test all worked. The last mile did not: every map component built its config
 * with `legacyMapProviderConfig(apiKey)`, which hardcodes Google, and the pages
 * decided whether to render a map by asking whether a *Google* key was present.
 * For any other provider that key is null -- correctly, the backend does not
 * return one provider's secret when another is chosen -- so the panel was empty
 * and nothing said why.
 *
 * These are the payloads the backend actually sends.
 */

const GOOGLE = {
    map_provider: 'google',
    map_credentials: { apiKey: 'AIzaTESTTESTTESTTESTTESTTESTTESTTESTTES', styleId: null },
    map_provider_missing: [],
    google_maps_api_key: 'AIzaTESTTESTTESTTESTTESTTESTTESTTESTTES',
    google_maps_map_id: null,
};

const ESRI = {
    map_provider: 'esri',
    map_credentials: { apiKey: 'esri-token', styleId: 'county-basemap', locatorUrl: 'https://gis.county/locator' },
    map_provider_missing: [],
    // The backend deliberately sends no Google key when Esri is selected.
    google_maps_api_key: null,
    google_maps_map_id: null,
};

const APPLE = {
    map_provider: 'apple',
    // No apiKey at all: MapKit wants a signed JWT, minted server-side because
    // the signing key must never reach a browser.
    map_credentials: { teamId: 'TEAM123456', keyId: 'KEY1234567', token: 'eyJhbGciOi.signed.jwt' },
    map_provider_missing: [],
    google_maps_api_key: null,
};

describe('the town gets the provider it chose', () => {
    it.each([
        ['google', GOOGLE, 'google'],
        ['esri', ESRI, 'esri'],
        ['apple', APPLE, 'apple'],
    ])('resolves %s rather than defaulting to Google', (_name, raw, expected) => {
        expect(resolveMapProviderConfig(raw as any).provider).toBe(expected);
    });

    it('falls back to Google only when nothing was chosen', () => {
        // An older payload, or a settings row written before maps became a
        // switchable capability. Falling back beats erroring: a town with no map
        // at all is worse than a town on the default.
        expect(resolveMapProviderConfig({}).provider).toBe('google');
        expect(resolveMapProviderConfig(null).provider).toBe('google');
        expect(resolveMapProviderConfig({ map_provider: 'nonsense' } as any).provider).toBe('google');
    });
});

describe('one provider never receives another provider credentials', () => {
    it('does not hand the Google key to a non-Google provider', () => {
        // The dangerous version of this bug is not "no map", it is a Google key
        // sent to the Esri adapter -- which turns "you have not finished setting
        // this up" into an authentication error from a vendor the town never
        // chose, and sends somebody to the wrong console.
        const raw = { ...ESRI, google_maps_api_key: 'AIzaLEAKLEAKLEAKLEAKLEAKLEAKLEAKLEAKLEA' };
        const config = resolveMapProviderConfig(raw as any);
        expect(config.provider).toBe('esri');
        expect(config.apiKey).toBe('esri-token');
    });

    it('carries provider-specific extras through to the adapter', () => {
        // Esri's county locator is, per the provider catalogue's own notes, the
        // single biggest local accuracy win available. It has to reach the
        // adapter or choosing it achieves nothing.
        expect(resolveMapProviderConfig(ESRI as any).options).toMatchObject({
            locatorUrl: 'https://gis.county/locator',
        });
    });

    it("renames Apple's minted token to what its adapter looks for", () => {
        // The wire calls it `token` for every provider that mints one; the Apple
        // adapter reads `options.mapkitToken`.
        expect(resolveMapProviderConfig(APPLE as any).options).toMatchObject({
            mapkitToken: 'eyJhbGciOi.signed.jwt',
        });
    });
});

describe('whether a map can be drawn at all', () => {
    it.each([
        ['google', GOOGLE],
        ['esri', ESRI],
        ['apple', APPLE],
    ])('says a fully configured %s town is ready', (_name, raw) => {
        expect(mapProviderReady(raw as any)).toBe(true);
    });

    it('says a half-configured town is not ready, whichever provider', () => {
        // The backend already worked this out per provider; the pages just never
        // asked. Reported rather than silently falling back to Google, so an
        // admin can see why their map is blank.
        expect(mapProviderReady({ map_provider: 'esri', map_credentials: {}, map_provider_missing: ['apiKey'] } as any)).toBe(false);
        expect(mapProviderReady(null)).toBe(false);
    });

    it('treats a token-only Apple town as credentialled', () => {
        // Not `!!apiKey`: Apple has no static key, so the obvious check would
        // report a correctly configured Apple town as unconfigured.
        expect(hasMapCredential(resolveMapProviderConfig(APPLE as any))).toBe(true);
        expect(hasMapCredential(resolveMapProviderConfig({ map_provider: 'apple', map_credentials: {} } as any))).toBe(false);
    });

    it('still works on a payload that predates the provider fields', () => {
        // Deployments upgrade at their own pace and this endpoint is public.
        const legacyOnly = { google_maps_api_key: 'AIzaOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOLDOL' };
        expect(mapProviderReady(legacyOnly)).toBe(true);
        expect(resolveMapProviderConfig(legacyOnly).apiKey).toBe(legacyOnly.google_maps_api_key);
    });
});
