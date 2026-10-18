// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
// `?raw` rather than fs: this file is type-checked with the app.
import CARD_SOURCE from './GovtechIntegrations.tsx?raw';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The mapping step and the failed-sync backlog, rendered.
 *
 * Every endpoint behind these existed with no screen, so the assertions are on
 * the DOM a clerk would see and on what a save actually posts.
 */

const getCategories = vi.fn();
const refreshLookups = vi.fn();
const saveMapping = vi.fn();
const getBacklog = vi.fn();
const getSyncProblems = vi.fn();
const retryBacklogItem = vi.fn();
const discardBacklogItem = vi.fn();

vi.mock('../services/integrationsApi', () => ({
    integrationsApi: {
        getCategories: (...a: unknown[]) => getCategories(...a),
        refreshLookups: (...a: unknown[]) => refreshLookups(...a),
        saveMapping: (...a: unknown[]) => saveMapping(...a),
        getBacklog: (...a: unknown[]) => getBacklog(...a),
        getSyncProblems: (...a: unknown[]) => getSyncProblems(...a),
        retryBacklogItem: (...a: unknown[]) => retryBacklogItem(...a),
        discardBacklogItem: (...a: unknown[]) => discardBacklogItem(...a),
    },
}));

import { MappingPanel, FailedSyncsPanel } from './IntegrationMapping';

const ARCGIS_PLATFORM: any = {
    platform: 'arcgis', name: 'Esri ArcGIS', vendor: 'Esri', category: 'GIS',
    integration_mode: 'public_api', docs_url: '', description: '',
    capabilities: ['push', 'push_status', 'pull', 'lookups', 'test'],
    credential_fields: [], config_fields: [], setup_notes: '', plain_summary: '',
    what_you_need: [], vendor_ask: null, field_help: {}, recommended_sync_direction: 'bidirectional',
    default_status_map_out: { open: 'Submitted', in_progress: 'Assigned', closed: 'Completed' },
    default_status_map_in: { submitted: 'open' },
    status_push: true,
};

const TYLER_PLATFORM: any = {
    ...ARCGIS_PLATFORM, platform: 'tyler', name: 'Tyler', integration_mode: 'open311',
    capabilities: ['push', 'pull', 'lookups', 'test'], status_push: false,
    default_status_map_out: { open: 'open', in_progress: 'open', closed: 'closed' },
    default_status_map_in: { open: 'open', closed: 'closed' },
};

const integration = (overrides: Record<string, unknown> = {}): any => ({
    id: 7, platform: 'arcgis', platform_name: 'Esri ArcGIS', display_name: 'ArcGIS', enabled: true,
    sync_direction: 'bidirectional', configured_credentials: [], credentials_vaulted: false,
    oauth_connected: false, webhook_path: '/x', last_sync_at: null, last_sync_status: null,
    last_sync_error: null, created_at: null,
    config: { service_code_map: { PTH: '1' }, share_pii: false },
    lookups: {
        services: [{ code: '1', name: 'Pothole' }, { code: '2', name: 'Light' }],
        statuses: [{ code: 'NEW', name: 'New' }, { code: 'DONE', name: 'Done' }],
        fields: [{ code: 'reqid', name: 'reqid' }, { code: 'notes', name: 'Notes' }],
        _source: { services: 'the reqtype domain' },
    },
    lookups_fetched_at: '2026-10-01T12:00:00Z',
    ...overrides,
});

let container: HTMLDivElement;
let root: Root;

async function mount(ui: React.ReactElement) {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => { root.render(ui); });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
}

function typeInto(el: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

const button = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(b => b.textContent?.includes(text)) as HTMLButtonElement;

beforeEach(() => {
    vi.clearAllMocks();
    getCategories.mockResolvedValue([
        { id: 1, service_code: 'PTH', service_name: 'Pothole', is_active: true },
        { id: 2, service_code: 'LGT', service_name: 'Streetlight', is_active: true },
        { id: 3, service_code: 'OLD', service_name: 'Retired', is_active: false },
    ]);
});

afterEach(() => {
    act(() => root.unmount());
    container.remove();
});

describe('MappingPanel', () => {
    it('asks Accela for its own priority values and saves them; Open311 has no priority section', async () => {
        const ACCELA: any = { ...ARCGIS_PLATFORM, platform: 'accela', name: 'Accela' };
        saveMapping.mockResolvedValue(integration({ platform: 'accela' }));
        await mount(<MappingPanel integration={integration({ platform: 'accela' })} platform={ACCELA} onSaved={() => { }} />);
        await act(async () => { button('Priority').click(); });
        expect(container.textContent).toContain('Accela only accepts your agency’s own priority values');
        await act(async () => { typeInto(container.querySelector('#map-priority-7-high') as HTMLInputElement, '1 - Emergency'); });
        await act(async () => { button('Save mapping').click(); });
        expect(saveMapping.mock.calls[0][1].priority_map_out).toEqual({ high: '1 - Emergency' });
        act(() => root.unmount());
        container.remove();

        await mount(<MappingPanel integration={integration({ platform: 'tyler' })} platform={TYLER_PLATFORM} onSaved={() => { }} />);
        expect(container.querySelector('[id^="map-priority-"]')).toBeNull();
    });

    it('lists each active category with a picker over the vendor values', async () => {
        await mount(<MappingPanel integration={integration()} platform={ARCGIS_PLATFORM} onSaved={() => { }} />);
        const pothole = container.querySelector('#map-cat-7-PTH') as HTMLInputElement;
        expect(pothole).toBeTruthy();
        // The legacy key's values are read as the outbound map.
        expect(pothole.value).toBe('1');
        const options = Array.from(container.querySelectorAll('#map-cat-7-PTH-options option')).map(o => (o as HTMLOptionElement).value);
        expect(options).toEqual(['1', '2']);
        expect(container.querySelector('#map-cat-7-OLD')).toBeNull();
        expect(container.textContent).toContain('Values from the reqtype domain');
    });

    it('shows status defaults as defaults, and saves explicit maps', async () => {
        const onSaved = vi.fn();
        saveMapping.mockResolvedValue({ ...integration(), mapping_approved_at: '2026-10-02T00:00:00Z' });
        await mount(<MappingPanel integration={integration()} platform={ARCGIS_PLATFORM} onSaved={onSaved} />);

        const out = container.querySelector('#map-out-7-in_progress') as HTMLInputElement;
        expect(out.placeholder).toBe('Default: Assigned');

        await act(async () => { typeInto(container.querySelector('#map-cat-7-LGT') as HTMLInputElement, '2'); });
        await act(async () => { typeInto(out, 'NEW'); });
        const pii = container.querySelector('button[aria-label="Send resident contact details"]') as HTMLButtonElement;
        await act(async () => { pii.click(); });
        await act(async () => { button('Save mapping').click(); });

        expect(saveMapping).toHaveBeenCalledTimes(1);
        const [id, body] = saveMapping.mock.calls[0];
        expect(id).toBe(7);
        expect(body.service_code_map_out).toEqual({ PTH: '1', LGT: '2' });
        expect(body.status_map_out).toEqual({ in_progress: 'NEW' });
        expect(body.share_pii).toBe(true);
        expect(body.import_new_records).toBe(false);
        expect(body.field_map).toEqual({});
        expect(onSaved).toHaveBeenCalled();
        expect(container.textContent).toContain('Mapping saved');
    });

    it('offers the layer columns behind a disclosure', async () => {
        await mount(<MappingPanel integration={integration()} platform={ARCGIS_PLATFORM} onSaved={() => { }} />);
        expect(container.querySelector('#map-field-7-description')).toBeNull();
        await act(async () => { button('Layer columns').click(); });
        const select = container.querySelector('#map-field-7-description') as HTMLSelectElement;
        const values = Array.from(select.options).map(o => o.value);
        expect(values).toContain('notes');
        expect(values).toContain('');  // "Don't send"
        expect(values).toContain('details');  // the default, flagged as missing
    });

    it('refreshes the vendor lists on request', async () => {
        refreshLookups.mockResolvedValue({ ok: true, supported: true, lookups: { services: [{ code: '9', name: 'Graffiti' }] }, fetched_at: '2026-10-03T00:00:00Z' });
        await mount(<MappingPanel integration={integration()} platform={ARCGIS_PLATFORM} onSaved={() => { }} />);
        await act(async () => { button('Refresh from Esri ArcGIS').click(); });
        expect(refreshLookups).toHaveBeenCalledWith(7);
        const options = Array.from(container.querySelectorAll('#map-cat-7-PTH-options option')).map(o => (o as HTMLOptionElement).value);
        expect(options).toEqual(['9']);
    });

    it('says plainly that Open311 cannot send status back', async () => {
        await mount(<MappingPanel integration={integration({ platform: 'tyler', config: { default_service_code: 'GEN' } })}
            platform={TYLER_PLATFORM} onSaved={() => { }} />);
        expect(container.textContent).toContain('Open311 has no way to send a status change back');
        expect(container.textContent).toContain('fallback service code (GEN)');
        expect(container.querySelector('#map-out-7-open')).toBeNull();
        expect(container.querySelector('[aria-label="Import reports filed in Tyler"]')).toBeTruthy();
    });
});

describe('FailedSyncsPanel', () => {
    const ITEM = {
        id: 31, operation: 'push', request_id: 'REQ-1', comment_id: null, attempts: 8,
        last_error: 'HTTP 401 — bad key', first_failed_at: null, last_attempt_at: null,
        next_attempt_at: null, stalled: true, resolved_at: null, resolution: null, resolution_note: null,
    };

    it('lists the backlog, link errors and warnings', async () => {
        getBacklog.mockResolvedValue([ITEM]);
        getSyncProblems.mockResolvedValue({
            link_errors: [{ request_id: 'REQ-2', external_id: 'token:abc', pending: true, error: 'Waiting for the vendor', last_pushed_at: null }],
            warnings: [{ id: 1, operation: 'push', detail: 'REQ-3: The layer has no column named "x"', created_at: null }],
        });
        await mount(<FailedSyncsPanel integration={integration()} platformName="ArcGIS" enabled={true} />);
        expect(container.textContent).toContain('New report');
        expect(container.textContent).toContain('HTTP 401');
        expect(container.textContent).toContain('No more automatic tries');
        expect(container.textContent).toContain('record number pending');
        expect(container.textContent).toContain('no column named');
    });

    it('retries an item', async () => {
        getBacklog.mockResolvedValue([ITEM]);
        getSyncProblems.mockResolvedValue({ link_errors: [], warnings: [] });
        retryBacklogItem.mockResolvedValue({ ok: true, started: true, detail: 'Trying again now.' });
        const onChanged = vi.fn();
        await mount(<FailedSyncsPanel integration={integration()} platformName="ArcGIS" enabled={true} onChanged={onChanged} />);
        await act(async () => { button('Retry').click(); });
        expect(retryBacklogItem).toHaveBeenCalledWith(7, 31);
        expect(onChanged).toHaveBeenCalled();
        expect(container.textContent).toContain('Trying again now.');
    });

    it('needs a reason to discard', async () => {
        getBacklog.mockResolvedValue([ITEM]);
        getSyncProblems.mockResolvedValue({ link_errors: [], warnings: [] });
        discardBacklogItem.mockResolvedValue({ ok: true, detail: 'Removed from the backlog.' });
        await mount(<FailedSyncsPanel integration={integration()} platformName="ArcGIS" enabled={true} />);
        await act(async () => { button('Discard').click(); });
        expect(button('Confirm discard').disabled).toBe(true);
        await act(async () => { typeInto(container.querySelector('[aria-label="Reason for not sending"]') as HTMLInputElement, 'Duplicate of REQ-9'); });
        await act(async () => { button('Confirm discard').click(); });
        expect(discardBacklogItem).toHaveBeenCalledWith(7, 31, 'Duplicate of REQ-9');
    });

    it('says when nothing is waiting', async () => {
        getBacklog.mockResolvedValue([]);
        getSyncProblems.mockResolvedValue({ link_errors: [], warnings: [] });
        await mount(<FailedSyncsPanel integration={integration()} platformName="ArcGIS" enabled={true} />);
        expect(container.textContent).toContain('Nothing waiting');
    });
});

describe('the connection card', () => {
    it('offers Mapping and Failed syncs on every connected card', () => {
        expect(CARD_SOURCE).toContain('<MappingPanel');
        expect(CARD_SOURCE).toContain('<FailedSyncsPanel');
        expect(CARD_SOURCE).toContain("togglePanel(platform.platform, 'mapping')");
        expect(CARD_SOURCE).toContain('Redirect URI to register');
    });
});
