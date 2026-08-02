/**
 * Single shared loader for the Google Maps JavaScript API.
 *
 * The API must be included on a page exactly once — loading the script tag more
 * than once triggers Google's "You have included the Google Maps JavaScript API
 * multiple times on this page" error (the "This page can't load Google Maps
 * correctly" dialog). Several components render a map, and more than one can be
 * mounted on the same page (e.g. the staff dashboard map + the manual-intake
 * location picker), so they must all go through this one guarded loader instead
 * of each appending their own <script>.
 */

let loadPromise: Promise<void> | null = null;

declare global {
    interface Window {
        google: typeof google;
    }
}

export function loadGoogleMaps(apiKey: string): Promise<void> {
    // Already fully loaded (including the Places library we always request).
    if (typeof window !== 'undefined' && window.google?.maps?.places) {
        return Promise.resolve();
    }
    if (loadPromise) return loadPromise;

    loadPromise = new Promise<void>((resolve, reject) => {
        // Reuse an existing tag if one is already on the page (guards against a
        // second component mounting before the first script has finished).
        const existing = document.querySelector('script[data-google-maps]') as HTMLScriptElement | null;
        if (existing) {
            if (window.google?.maps) return resolve();
            existing.addEventListener('load', () => resolve());
            existing.addEventListener('error', () => { loadPromise = null; reject(new Error('Failed to load Google Maps')); });
            return;
        }

        const callbackName = '__pinpointInitGoogleMaps__';
        (window as unknown as Record<string, unknown>)[callbackName] = async () => {
            // Wait for the libraries, not just the bootstrap.
            //
            // With `loading=async` the callback fires once the core is ready.
            // The libraries named in `libraries=` are fetched alongside it and
            // are not guaranteed to be on `window.google.maps` at that moment,
            // so a component mounting immediately can find `maps.places`
            // undefined -- and `attachAutocomplete` correctly answers "this
            // provider has no widget", which is the right answer to the wrong
            // question. The input then falls back to a plain text box for the
            // rest of the page's life, because nothing retries.
            //
            // `importLibrary` is idempotent and resolves from cache once
            // loaded, so awaiting it here costs nothing after the first call.
            try {
                const maps = window.google?.maps as unknown as {
                    importLibrary?: (name: string) => Promise<unknown>;
                };
                if (typeof maps?.importLibrary === 'function') {
                    await Promise.all([
                        maps.importLibrary('places'),
                        maps.importLibrary('geocoding'),
                    ]);
                }
            } catch {
                // A library that will not load is a real failure, but it is the
                // geocoder's to report -- it already degrades to the backend
                // provider. Resolving here keeps the *map* working, which is
                // the larger half of what this script is for.
            }
            resolve();
            try { delete (window as unknown as Record<string, unknown>)[callbackName]; } catch { /* ignore */ }
        };

        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places&loading=async&callback=${callbackName}`;
        script.async = true;
        script.defer = true;
        script.setAttribute('data-google-maps', 'true');
        script.onerror = () => { loadPromise = null; reject(new Error('Failed to load Google Maps')); };
        document.head.appendChild(script);
    });

    return loadPromise;
}
