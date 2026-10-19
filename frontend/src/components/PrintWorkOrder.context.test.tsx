// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The work order prints the report's location context -- the parcel or zone
 * it fell in, as recorded at intake -- with the layer's allowlisted fields.
 * Values come from an uploaded GIS file, so they are escaped exactly once.
 */
import PrintWorkOrder from './PrintWorkOrder';
import { AccessibilityProvider } from '../context/AccessibilityContext';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}

const EVIL = '<img src=x onerror="alert(1)">';

const request = {
    service_request_id: 'REQ-1', service_name: 'Pothole', service_code: 'pothole', status: 'open',
    closed_substatus: null, description: 'Deep hole', address: '1 Main St', lat: null, long: null,
    requested_datetime: '2026-06-03T10:00:00Z', updated_datetime: null, closed_datetime: null,
    email: 'r@example.test', first_name: null, last_name: null, source: 'resident_portal',
    media_urls: [], custom_fields: {}, matched_asset: null, staff_notes: null, ai_analysis: null,
    manual_priority_score: null,
    gis_context: [
        { layer_id: 3, layer_name: 'Tax Parcels', feature_id: 9, feature_key: '12-4',
          label: "O'Brien Farm & Barn", properties: { PAMS_PIN: '12-4', ZONE_CODE: `R-1 ${EVIL}`, ACRES: 2.5 } },
        { layer_id: 4, layer_name: 'Wards', feature_id: 2, feature_key: 'W2', label: 'W2', properties: {} },
    ],
} as any;

let written = '';
afterEach(() => { cleanup(); vi.restoreAllMocks(); written = ''; });

describe('location context on the work order', () => {
    it('prints each layer, label and allowlisted field, escaped once', async () => {
        const user = userEvent.setup();
        vi.spyOn(window, 'open').mockReturnValue({
            document: { write: (html: string) => { written += html; }, close: () => { } },
            print: vi.fn(), onload: null,
        } as any);
        render(
            <AccessibilityProvider>
                <PrintWorkOrder request={request} comments={[]} auditLog={[]} townshipName="Town" />
            </AccessibilityProvider>,
        );
        await user.click(screen.getByRole('button', { name: /print work order/i }));
        expect(written).toContain('Location Context');
        expect(written).toContain('Tax Parcels');
        expect(written).toContain('O&#39;Brien Farm &amp; Barn');
        expect(written).not.toContain('&amp;amp;');
        expect(written).not.toContain('&amp;#39;');
        expect(written).toContain('Zone Code:');
        expect(written).toContain('2.5');
        expect(written).not.toContain('<img src=x');
        // The second layer, whose label is its ID.
        expect(written).toContain('<strong>ID:</strong> W2');
    });

    it('prints nothing when the report has no context', async () => {
        const user = userEvent.setup();
        vi.spyOn(window, 'open').mockReturnValue({
            document: { write: (html: string) => { written += html; }, close: () => { } },
            print: vi.fn(), onload: null,
        } as any);
        render(
            <AccessibilityProvider>
                <PrintWorkOrder request={{ ...request, gis_context: null }} comments={[]} auditLog={[]} townshipName="Town" />
            </AccessibilityProvider>,
        );
        await user.click(screen.getByRole('button', { name: /print work order/i }));
        expect(written).not.toContain('Location Context');
    });
});
