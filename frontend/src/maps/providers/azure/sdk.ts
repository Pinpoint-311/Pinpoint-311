/**
 * Guarded, lazy load of the Azure Maps Web SDK.
 *
 * Same shape as the Google loader: nothing happens until a town actually
 * selects Azure. The `import()` keeps azure-maps-control (and its stylesheet)
 * out of every other town's bundle; only `import type` is allowed elsewhere in
 * this directory.
 */

type AtlasModule = typeof import('azure-maps-control');

let sdk: AtlasModule | null = null;
let loading: Promise<void> | null = null;

export function loadAzureMaps(): Promise<void> {
    if (sdk) return Promise.resolve();
    if (loading) return loading;

    loading = (async () => {
        const [module] = await Promise.all([
            import('azure-maps-control'),
            // Positions the canvas, controls, HTML markers and popups.
            import('azure-maps-control/dist/atlas.min.css'),
        ]);
        sdk = module;
    })().catch(error => {
        loading = null;
        throw error;
    });

    return loading;
}

export function atlasSdk(): AtlasModule {
    if (!sdk) throw new Error('Azure Maps has not been loaded yet');
    return sdk;
}
