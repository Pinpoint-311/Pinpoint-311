/* eslint-disable @typescript-eslint/no-explicit-any */

let loadingPromise: Promise<void> | null = null;
let cachedAtlas: any = null;

export function loadAzureMaps(): Promise<void> {
    if (cachedAtlas) return Promise.resolve();
    if (loadingPromise) return loadingPromise;

    loadingPromise = new Promise((resolve, reject) => {
        if ((window as any).atlas) {
            cachedAtlas = (window as any).atlas;
            resolve();
            return;
        }

        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.css";
        document.head.appendChild(link);

        const script = document.createElement("script");
        script.src = "https://atlas.microsoft.com/sdk/javascript/mapcontrol/3/atlas.min.js";
        script.async = true;
        script.onload = () => {
            cachedAtlas = (window as any).atlas;
            resolve();
        };
        script.onerror = () => {
            loadingPromise = null;
            reject(new Error("Failed to load Azure Maps Web SDK"));
        };
        document.head.appendChild(script);
    });

    return loadingPromise;
}

export function atlasSdk(): any {
    if (!cachedAtlas && (window as any).atlas) {
        cachedAtlas = (window as any).atlas;
    }
    if (!cachedAtlas) throw new Error("Azure Maps has not been loaded yet");
    return cachedAtlas;
}
