// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The work order is an HTML string written into a same-origin window. Every
 * value from a resident, a commenter, a custom question or an asset must be
 * escaped, or markup in it runs as script in a signed-in staff session when
 * someone prints.
 */
import PrintWorkOrder, { escapeHtml } from './PrintWorkOrder';
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
    service_request_id: 'REQ-1',
    service_name: `Pothole ${EVIL}`,
    service_code: 'pothole',
    status: 'open',
    closed_substatus: null,
    description: `Deep hole <script>alert(2)</script> ${EVIL}`,
    address: `12 Main St ${EVIL}`,
    lat: null,
    long: null,
    requested_datetime: '2026-06-03T10:00:00Z',
    updated_datetime: '2026-06-04T10:00:00Z',
    closed_datetime: null,
    email: 'resident@example.test',
    first_name: `Ada ${EVIL}`,
    last_name: 'Lovelace',
    source: 'resident_portal',
    media_urls: ['javascript:alert(3)', 'https://town.example/a.jpg" onerror="alert(4)'],
    completion_photo_url: 'javascript:alert(5)',
    custom_fields: { [`Label ${EVIL}`]: `Answer ${EVIL}` },
    matched_asset: { layer_name: `Hydrants ${EVIL}`, asset_id: 'H-1', properties: { note: EVIL } },
    staff_notes: `Note ${EVIL}`,
    ai_analysis: { qualitative_analysis: `AI ${EVIL}` },
    manual_priority_score: null,
} as any;

const comments = [
    { id: 1, content: `Public comment ${EVIL}`, username: `bob ${EVIL}`, visibility: 'external', created_at: '2026-06-04T10:00:00Z' },
] as any;

let written = '';
const fakeWindow = () => ({
    document: { write: (html: string) => { written += html; }, close: () => { } },
    print: vi.fn(),
    onload: null as null | (() => void),
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); written = ''; });

describe('the printed work order', () => {
    it('escapes every value from residents, commenters, custom questions and assets', async () => {
        const user = userEvent.setup();
        vi.spyOn(window, 'open').mockReturnValue(fakeWindow() as any);
        render(
            <AccessibilityProvider>
                <PrintWorkOrder request={request} comments={comments} townshipName={`Town ${EVIL}`} />
            </AccessibilityProvider>,
        );
        await user.click(screen.getByRole('button', { name: /print work order/i }));

        expect(written.length).toBeGreaterThan(1000);
        expect(written).not.toContain('<img src=x');
        expect(written).not.toContain('<script>alert(2)');
        expect(written).not.toContain('onerror="alert');
        expect(written).not.toContain('javascript:alert');
        expect(written).toContain('&lt;script&gt;alert(2)&lt;/script&gt;');
    });

    it('escapeHtml covers the characters that break out of text and attributes', () => {
        expect(escapeHtml(`<a href="x" onclick='y'>&\``)).toBe('&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;&#96;');
        expect(escapeHtml(null)).toBe('');
    });
});
