import { loadMapProvider } from './registry';
import type { MapProviderConfig } from './types';

/**
 * Does the map actually draw for a resident? Asked in a browser, because that is
 * the only place the question has an answer.
 *
 * A server cannot answer it. Google enforces its HTTP referrer restriction when
 * a map initialises, not when the script is fetched -- `maps/api/js` returns
 * byte-identical JS for any `Referer`, so there is nothing for a server to
 * inspect. Worse, the two states read backwards from a server:
 *
 *   key restricted to Websites      correct, and *rejects* the server
 *   key restricted to IP addresses  accepts the server, and fails every
 *                                   resident with RefererNotAllowedMapError
 *
 * So the server's verdict was inverted for the case that matters, and the page
 * could only hedge. This does the real thing: load the town's configured
 * provider and build a real map, from the town's own origin. The referrer is
 * correct by construction, because this *is* the site.
 *
 * Provider-agnostic, and the same check for every provider. Esri, Azure and
 * MapKit all reject their load or throw from the constructor when a credential
 * is refused, so `createRenderer` failing is the answer for them. Google
 * resolves normally and calls a global hook instead, which is what
 * `watchAuthFailure` on the factory is for -- see providers/google/index.ts. A
 * provider without that hook is not treated as passing by default; it is held to
 * the same "a map was built and did not fail" bar as the rest.
 */

export type BrowserMapVerdict = {
    ok: boolean;
    /** Shown to the administrator: what happened, then what to do about it. */
    detail: string;
    /** False when the check could not reach a conclusion, rather than failing. */
    conclusive: boolean;
};

/** How long to give the SDK to complain before believing the map is fine. */
const SETTLE_MS = 4_000;

export async function checkMapInBrowser(
    config: MapProviderConfig,
    { settleMs = SETTLE_MS }: { settleMs?: number } = {},
): Promise<BrowserMapVerdict> {
    if (typeof document === 'undefined' || typeof window === 'undefined') {
        return { ok: false, conclusive: false, detail: 'No browser to check in.' };
    }
    if (!config.provider) {
        return { ok: false, conclusive: false, detail: 'No map provider is selected yet.' };
    }

    const origin = window.location.origin;

    /* Off-screen, but laid out. A map in a zero-size or `display:none` container
     * never requests a tile, so it would pass without asking the provider
     * anything -- which is exactly the bug being tested for. */
    const probe = document.createElement('div');
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText =
        'position:absolute;left:-10000px;top:0;width:320px;height:240px;pointer-events:none';
    document.body.appendChild(probe);

    let watch: { failed: () => boolean; stop: () => void } | undefined;

    try {
        const factory = await loadMapProvider(config.provider);

        // Armed before the SDK runs, or a failure that arrives promptly is missed.
        watch = factory.watchAuthFailure?.();

        await factory.load(config);
        const map = factory.createRenderer(probe, config, {
            center: { lat: 40.7128, lng: -74.006 },
            zoom: 12,
        });

        /* Out-of-band failures arrive after construction returns, once the first
         * tile request has come back refused. Returning immediately would report
         * success on precisely the key this exists to catch. Providers that throw
         * have already thrown by now, so this only costs time when there is a
         * hook that might still fire. */
        if (watch) {
            await new Promise<void>(resolve => {
                const started = Date.now();
                const poll = () => {
                    if (watch!.failed() || Date.now() - started > settleMs) return resolve();
                    window.setTimeout(poll, 150);
                };
                window.setTimeout(poll, 300);
            });
        }

        const refused = watch?.failed() === true;
        try { map.destroy(); } catch { /* already gone */ }

        if (refused) {
            return {
                ok: false,
                conclusive: true,
                detail: `The map will not draw for residents: ${config.provider} refused this `
                    + `credential for ${origin}. For Google, open the key in Google Cloud and set `
                    + `Application restrictions to "Websites" with ${origin}/* on the list — a key `
                    + 'restricted to "IP addresses" passes a server check and fails in every browser.',
            };
        }

        return {
            ok: true,
            conclusive: true,
            detail: `The map drew in this browser from ${origin}, so it will draw for residents.`,
        };
    } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        /* A load that never arrives is often the Content-Security-Policy
         * refusing the SDK's host, which looks nothing like a credential problem
         * and would otherwise be reported as one. */
        return {
            ok: false,
            conclusive: true,
            detail: `The map could not be created in this browser: ${message}. If the browser `
                + "console shows a Content-Security-Policy error, the provider's script host is "
                + 'not permitted rather than the credential being wrong.',
        };
    } finally {
        watch?.stop();
        probe.remove();
    }
}
