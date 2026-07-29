/**
 * Guarded CDN loader for Apple MapKit JS.
 *
 * MapKit JS may only be loaded from Apple's CDN — there is no npm distribution
 * and self-hosting the bundle violates the terms — so this is a script-tag
 * loader like src/utils/googleMaps.ts, with the same one-tag-per-page rule.
 *
 * Authentication is a JWT (ES256, signed with a MapKit JS private key from an
 * Apple Developer account) that Pinpoint's backend must mint; the browser never
 * sees the key. MapKit calls the authorization callback again whenever the
 * token nears expiry, which is why `tokenUrl` exists alongside a static token:
 * a static JWT stops working when it expires and the map dies mid-session.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

const DEFAULT_VERSION = '5.x.x';
const SCRIPT_MARKER = 'data-apple-mapkit';

export interface AppleLoadOptions {
    /** Static JWT. Simple, but the map stops working when it expires. */
    token?: string | null;
    /**
     * Endpoint returning a fresh JWT — either `{"token": "..."}` or the raw
     * string. Re-fetched on every MapKit authorization request, so long-lived
     * sessions keep working.
     */
    tokenUrl?: string | null;
    /** MapKit JS version path segment on the CDN. */
    version?: string;
    /** Full script URL override. */
    scriptUrl?: string;
    /** BCP-47 language for map labels and geocoding results. */
    language?: string;
}

let loadPromise: Promise<any> | null = null;
let cached: any = null;

async function fetchToken(url: string): Promise<string> {
    const response = await fetch(url, { credentials: 'include' });
    if (!response.ok) throw new Error(`MapKit token endpoint failed: ${response.status}`);

    const text = await response.text();
    try {
        const parsed = JSON.parse(text);
        const token = parsed?.token ?? parsed?.mapkitToken ?? parsed?.jwt;
        if (typeof token === 'string') return token;
    } catch {
        // Not JSON — the endpoint returned the bare JWT.
    }
    return text.trim();
}

function ensureScript(url: string): Promise<void> {
    const existing = document.querySelector(`script[${SCRIPT_MARKER}]`) as HTMLScriptElement | null;
    if (existing) {
        if ((window as any).mapkit) return Promise.resolve();
        return new Promise((resolve, reject) => {
            existing.addEventListener('load', () => resolve());
            existing.addEventListener('error', () => reject(new Error('Failed to load Apple MapKit JS')));
        });
    }

    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = url;
        script.async = true;
        // Apple's CDN requires the crossorigin attribute; without it MapKit
        // refuses to initialise with an opaque "unauthorized" error.
        script.crossOrigin = 'anonymous';
        script.setAttribute(SCRIPT_MARKER, 'true');
        script.onload = () => resolve();
        script.onerror = () => reject(new Error('Failed to load Apple MapKit JS'));
        document.head.appendChild(script);
    });
}

/**
 * mapkit.init() is fire-and-forget; authorisation happens asynchronously and is
 * reported through `configuration-change` / `error`. Resolving on 'Initialized'
 * means a rejected JWT surfaces as a failed load() instead of a blank map.
 */
function initialise(mapkit: any, options: AppleLoadOptions): Promise<void> {
    return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (err?: Error) => {
            if (settled) return;
            settled = true;
            mapkit.removeEventListener('configuration-change', onChange);
            mapkit.removeEventListener('error', onError);
            if (err) reject(err); else resolve();
        };
        const onChange = (event: any) => {
            if (event?.status === 'Initialized' || event?.status === 'Refreshed') finish();
        };
        const onError = (event: any) => finish(new Error(`MapKit JS error: ${event?.status ?? 'unknown'}`));

        mapkit.addEventListener('configuration-change', onChange);
        mapkit.addEventListener('error', onError);

        mapkit.init({
            authorizationCallback: (done: (token: string) => void) => {
                if (options.tokenUrl) {
                    fetchToken(options.tokenUrl)
                        .then(done)
                        .catch(err => finish(err instanceof Error ? err : new Error(String(err))));
                    return;
                }
                if (options.token) { done(options.token); return; }
                finish(new Error('Apple MapKit requires a JWT (mapkitToken or mapkitTokenUrl)'));
            },
            language: options.language,
        });

        // MapKit stays silent if the token is structurally valid but the origin
        // is not on the key's allow-list; do not hang the caller forever.
        setTimeout(() => finish(new Error('Apple MapKit JS did not initialise (check token origin allow-list)')), 20000);
    });
}

export function loadAppleMapKit(options: AppleLoadOptions = {}): Promise<any> {
    if (loadPromise) return loadPromise;

    const version = options.version || DEFAULT_VERSION;
    const scriptUrl = options.scriptUrl || `https://cdn.apple-mapkit.com/mk/${version}/mapkit.js`;

    loadPromise = (async () => {
        await ensureScript(scriptUrl);
        const mapkit = (window as any).mapkit;
        if (!mapkit) throw new Error('Apple MapKit JS loaded but window.mapkit is missing');

        await initialise(mapkit, options);
        cached = mapkit;
        return mapkit;
    })().catch(err => {
        loadPromise = null;
        throw err;
    });

    return loadPromise;
}

/** MapKit namespace for code that runs after load() and cannot await. */
export function appleMapKit(): any {
    if (!cached) throw new Error('MapKit JS not loaded — call loadAppleMapKit() first');
    return cached;
}
