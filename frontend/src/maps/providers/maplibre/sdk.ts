/**
 * Guarded, lazy load of the MapLibre GL bundle.
 *
 * The `import()` is the point: it puts maplibre-gl (roughly a megabyte of JS
 * plus its stylesheet) in its own chunk so a Google town never downloads it.
 * Nothing else in the adapter may import 'maplibre-gl' for a value — only
 * `import type`, which the compiler erases.
 */

type MapLibreModule = typeof import('maplibre-gl');

let sdk: MapLibreModule | null = null;
let loading: Promise<void> | null = null;

export function loadMapLibre(): Promise<void> {
    if (sdk) return Promise.resolve();
    if (loading) return loading;

    loading = (async () => {
        const [module] = await Promise.all([
            import('maplibre-gl'),
            // The stylesheet positions the canvas, controls, markers and popups;
            // without it the map renders as a collapsed, unstyled div.
            import('maplibre-gl/dist/maplibre-gl.css'),
        ]);
        sdk = module;
    })().catch(error => {
        // Let a transient network failure be retried rather than latching.
        loading = null;
        throw error;
    });

    return loading;
}

export function ml(): MapLibreModule {
    if (!sdk) throw new Error('MapLibre GL has not been loaded yet');
    return sdk;
}
