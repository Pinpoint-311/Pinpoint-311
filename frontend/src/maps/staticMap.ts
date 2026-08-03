import { MapProviderConfig } from './types';

/**
 * A picture of one location, for places that cannot run a map.
 *
 * The printed work order is the only such place: it is assembled as an HTML
 * string and handed to a print window, so it cannot mount a renderer.
 *
 * It used to build this inline:
 *
 *     https://www.google.com/maps/embed/v1/place?key=${mapsApiKey}&...
 *
 * which is Google whatever the town chose, so a town on Esri or Azure printed a
 * work order with an empty rectangle where the location should be, and one on
 * Apple printed nothing. The point of moving it here is that the component stops
 * knowing about vendors -- not that Google should start using a different API.
 *
 * ## Why this returns a kind and not just a URL
 *
 * The providers do not agree on what a picture of a place is. Azure and Esri
 * serve a PNG from a URL, which is the better answer for print. Google's
 * equivalent is the Maps Static API -- a *separate* product from the Maps Embed
 * API this replaced, and from the three the setup guide asks a town to enable.
 * On a real town's key, Embed answered 200 and Static answered
 *
 *     "This API is not activated on your API project"
 *
 * so returning a Static URL for Google would have swapped a working map for a
 * broken image on every printed work order, in the name of tidiness. Google
 * therefore keeps the embed it already has, and the caller renders whichever
 * kind it is handed.
 *
 * `null` is a real answer: Apple's snapshot service wants a request signed with a
 * key that must never reach a browser. Callers print the address and coordinates
 * instead, which is what a crew in a van actually needs.
 */

export interface MapSnapshotRequest {
    lat: number;
    lng: number;
    zoom?: number;
    width?: number;
    height?: number;
    /** Falls back to the provider's default style when unsupported. */
    mapType?: 'satellite' | 'roadmap';
}

export type MapSnapshot =
    /** A plain image URL. Print-safe. */
    | { kind: 'image'; url: string }
    /** An interactive embed that must go in an iframe. */
    | { kind: 'embed'; url: string };

export function mapSnapshot(
    config: MapProviderConfig | null | undefined,
    { lat, lng, zoom = 17, width = 640, height = 300, mapType = 'satellite' }: MapSnapshotRequest,
): MapSnapshot | null {
    if (!config || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    const key = config.apiKey;

    switch (config.provider) {
        case 'google': {
            if (!key) return null;
            // Maps Embed API -- deliberately, see the note above.
            const params = new URLSearchParams({
                key,
                q: `${lat},${lng}`,
                zoom: String(zoom),
                maptype: mapType === 'satellite' ? 'satellite' : 'roadmap',
            });
            return { kind: 'embed', url: `https://www.google.com/maps/embed/v1/place?${params}` };
        }

        case 'azure': {
            if (!key) return null;
            const params = new URLSearchParams({
                'api-version': '2024-04-01',
                'subscription-key': key,
                center: `${lng},${lat}`,
                zoom: String(zoom),
                width: String(width),
                height: String(height),
                tilesetId: mapType === 'satellite' ? 'microsoft.imagery' : 'microsoft.base.road',
                pins: `default||${lng} ${lat}`,
            });
            return { kind: 'image', url: `https://atlas.microsoft.com/map/static?${params}` };
        }

        case 'esri': {
            // ArcGIS exports an image from a map service over a bounding box
            // rather than from a point, so this converts the requested zoom into
            // one: Web Mercator spans 360 degrees over 256 pixels at zoom 0.
            const span = 360 / 256 / Math.pow(2, zoom);
            const halfW = (span * width) / 2;
            const halfH = (span * height) / 2;
            const service = mapType === 'satellite' ? 'World_Imagery' : 'World_Street_Map';
            const params = new URLSearchParams({
                bbox: `${lng - halfW},${lat - halfH},${lng + halfW},${lat + halfH}`,
                bboxSR: '4326',
                imageSR: '3857',
                size: `${width},${height}`,
                format: 'png',
                f: 'image',
            });
            if (key) params.set('token', key);
            return {
                kind: 'image',
                url: `https://services.arcgisonline.com/arcgis/rest/services/${service}/MapServer/export?${params}`,
            };
        }

        // Apple: a Web Snapshot must be signed server-side, and there is nothing
        // honest to return from here.
        default:
            return null;
    }
}
