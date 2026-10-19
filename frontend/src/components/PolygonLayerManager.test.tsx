import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';

const api = vi.hoisted(() => ({
    startLayerUpload: vi.fn(),
    uploadLayerChunk: vi.fn(),
    discardLayerUpload: vi.fn(),
    createPolygonLayer: vi.fn(),
    reuploadLayerFeatures: vi.fn(),
    backfillLayerContext: vi.fn(),
    updateMapLayer: vi.fn(),
    getServices: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));
const dialog = vi.hoisted(() => ({ confirm: vi.fn(), alert: vi.fn() }));
vi.mock('./DialogProvider', () => ({ useDialog: () => dialog }));

import { ContextLayerSettingsModal, uploadInChunks } from './PolygonLayerManager';

const SERVER_MAX = 500 * 1024 * 1024;

const layer = {
    id: 7, name: 'Tax Parcels', fill_color: '#f59e0b', stroke_color: '#b45309', fill_opacity: 0.1,
    stroke_width: 1, geojson: { type: 'FeatureCollection', features: [] }, is_active: true,
    show_on_resident_portal: false, visible_on_map: true, routing_mode: 'context' as const,
    feature_storage: 'table' as const, feature_id_property: 'PAMS_PIN', label_property: null,
    staff_properties: [], available_properties: ['PAMS_PIN', 'ZONE', 'OWNER_NAME', 'ST_NAME'],
    field_flags: { OWNER_NAME: 'owner' as const, ST_NAME: 'maybe' as const }, feature_count: 31234,
};

describe('uploadInChunks', () => {
    afterEach(() => vi.clearAllMocks());

    it('sends the file in parts no larger than the server asked for', async () => {
        api.startLayerUpload.mockResolvedValue({ upload_id: 'u1', chunk_bytes: 4, max_bytes: SERVER_MAX });
        api.uploadLayerChunk.mockResolvedValue({});
        const id = await uploadInChunks(new Blob(['0123456789']));
        expect(id).toBe('u1');
        expect(api.startLayerUpload).toHaveBeenCalledWith(10);
        expect(api.uploadLayerChunk.mock.calls.map(c => [c[1], (c[2] as Blob).size])).toEqual([[0, 4], [1, 4], [2, 2]]);
    });

    it('discards a half-finished upload', async () => {
        api.startLayerUpload.mockResolvedValue({ upload_id: 'u2', chunk_bytes: 4, max_bytes: SERVER_MAX });
        api.uploadLayerChunk.mockRejectedValueOnce(new Error('network'));
        api.discardLayerUpload.mockResolvedValue(undefined);
        await expect(uploadInChunks(new Blob(['0123456789']))).rejects.toThrow('network');
        expect(api.discardLayerUpload).toHaveBeenCalledWith('u2');
    });

    it('takes the limit from the server, not from the console', async () => {
        // The server refuses an oversized start with its own limit in the message.
        api.startLayerUpload.mockRejectedValueOnce(new Error('The file is 600 MB; the limit is 500 MB. Split the layer.'));
        const big = { size: 600 * 1048576, slice: () => new Blob() } as unknown as Blob;
        await expect(uploadInChunks(big)).rejects.toThrow(/the limit is 500 MB/);
        expect(api.uploadLayerChunk).not.toHaveBeenCalled();

        // And the max_bytes it answers with is the one the console checks against.
        api.startLayerUpload.mockResolvedValueOnce({ upload_id: 'u3', chunk_bytes: 4, max_bytes: 8 });
        api.discardLayerUpload.mockResolvedValue(undefined);
        await expect(uploadInChunks(new Blob(['0123456789']))).rejects.toThrow(/the limit is 0 MB/);
        expect(api.uploadLayerChunk).not.toHaveBeenCalled();
        expect(api.discardLayerUpload).toHaveBeenCalledWith('u3');

        // A file at or under a larger server limit goes up: nothing is fixed at 100 MB any more.
        api.startLayerUpload.mockResolvedValueOnce({ upload_id: 'u4', chunk_bytes: 1 << 30, max_bytes: SERVER_MAX });
        api.uploadLayerChunk.mockResolvedValue({});
        const mid = { size: 300 * 1048576, slice: () => new Blob(['x']) } as unknown as Blob;
        await expect(uploadInChunks(mid)).resolves.toBe('u4');
    });
});

const services = [
    { id: 1, service_code: 'potholes', service_name: 'Potholes' },
    { id: 2, service_code: 'streetlights', service_name: 'Streetlights' },
    { id: 3, service_code: 'graffiti', service_name: 'Graffiti' },
];

describe('ContextLayerSettingsModal', () => {
    beforeEach(() => {
        api.updateMapLayer.mockImplementation(async (_id, body) => ({ ...layer, ...body, warnings: [] }));
        api.getServices.mockResolvedValue(services);
    });
    afterEach(() => { cleanup(); vi.clearAllMocks(); });

    const open = (overrides = {}) => render(
        <ContextLayerSettingsModal layer={{ ...layer, ...overrides }} isOpen onClose={() => {}} onSaved={() => {}} />,
    );

    it('starts with no staff fields chosen and marks fields that look personal', () => {
        open();
        const boxes = ['PAMS_PIN', 'ZONE', 'OWNER_NAME', 'ST_NAME'].map(f => screen.getByRole('checkbox', { name: new RegExp(f) }) as HTMLInputElement);
        expect(boxes.every(b => !b.checked)).toBe(true);
        expect(screen.getByText('Owner details')).toBeTruthy();
        expect(screen.getByText('May be personal')).toBeTruthy();
    });

    it('keeps the resident portal off until fields are chosen, and off with owner fields', () => {
        open();
        const portal = () => screen.getByRole('switch', { name: /show on the resident portal/i }) as HTMLButtonElement;
        expect(portal().disabled).toBe(true);
        expect(screen.getByText(/choose the fields staff see first/i)).toBeTruthy();
        fireEvent.click(screen.getByRole('checkbox', { name: /ZONE/ }));
        expect(portal().disabled).toBe(false);
        fireEvent.click(screen.getByRole('checkbox', { name: /OWNER_NAME/ }));
        expect(portal().disabled).toBe(true);
        expect(screen.getByText(/owner details are among the staff fields \(OWNER_NAME\)/i)).toBeTruthy();
    });

    it('saves the purpose, fields and portal choice', async () => {
        const saved = vi.fn();
        render(<ContextLayerSettingsModal layer={layer} isOpen onClose={() => {}} onSaved={saved} />);
        fireEvent.click(screen.getByRole('checkbox', { name: /PAMS_PIN/ }));
        fireEvent.click(screen.getByRole('checkbox', { name: /ZONE/ }));
        fireEvent.change(screen.getByLabelText('Label field'), { target: { value: 'ST_NAME' } });
        fireEvent.click(screen.getByRole('switch', { name: /show on the resident portal/i }));
        fireEvent.click(screen.getByRole('button', { name: /save settings/i }));
        await waitFor(() => expect(saved).toHaveBeenCalled());
        expect(api.updateMapLayer).toHaveBeenCalledWith(7, expect.objectContaining({
            routing_mode: 'context', feature_id_property: 'PAMS_PIN', label_property: 'ST_NAME',
            staff_properties: ['PAMS_PIN', 'ZONE'], show_on_resident_portal: true,
        }));
    });

    it('shows what the server warns about', async () => {
        api.updateMapLayer.mockResolvedValueOnce({ ...layer, staff_properties: ['ST_NAME'], warnings: ['Check that these fields are not personal information: ST_NAME.'] });
        open();
        fireEvent.click(screen.getByRole('button', { name: /save settings/i }));
        expect(await screen.findByText(/not personal information: ST_NAME/)).toBeTruthy();
    });

    it('backfills only after confirming', async () => {
        dialog.confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
        api.backfillLayerContext.mockResolvedValue({ scanned: 1200, updated: 340 });
        open();
        const button = screen.getByRole('button', { name: /record on existing reports/i });
        fireEvent.click(button);
        await waitFor(() => expect(dialog.confirm).toHaveBeenCalledTimes(1));
        expect(api.backfillLayerContext).not.toHaveBeenCalled();
        fireEvent.click(button);
        expect(await screen.findByText(/340 now carry/)).toBeTruthy();
        expect(api.backfillLayerContext).toHaveBeenCalledWith(7);
    });

    it('offers both category pickers, defaulting to all categories', async () => {
        open();
        const staffGroup = screen.getByRole('group', { name: /record on reports in/i });
        const residentGroup = screen.getByRole('group', { name: /show outlines to residents in/i });
        expect(within(staffGroup).getByRole('radio', { name: 'All categories' })).toHaveProperty('checked', true);
        expect(within(residentGroup).getByRole('radio', { name: 'All categories' })).toHaveProperty('checked', true);
        expect(api.getServices).toHaveBeenCalled();
        // Each section is a heading a screen-reader user can jump between.
        for (const name of ['Purpose', 'Identify features', 'What staff see', 'Visibility', 'Categories', 'Data']) {
            expect(screen.getByRole('heading', { level: 3, name })).toBeTruthy();
        }
    });

    it('keeps the resident picker disabled, with the reason, while the portal is off', () => {
        open();
        const residentGroup = screen.getByRole('group', { name: /show outlines to residents in/i }) as HTMLFieldSetElement;
        expect(residentGroup.disabled).toBe(true);
        expect(within(residentGroup).getByText(/turn on .show on the resident portal. to choose/i)).toBeTruthy();
        fireEvent.click(screen.getByRole('checkbox', { name: /ZONE/ }));
        fireEvent.click(screen.getByRole('switch', { name: /show on the resident portal/i }));
        expect(residentGroup.disabled).toBe(false);
        // A display-only layer is recorded on nothing, so its staff picker is off.
        fireEvent.click(screen.getByRole('radio', { name: /display only/i }));
        expect((screen.getByRole('group', { name: /record on reports in/i }) as HTMLFieldSetElement).disabled).toBe(true);
    });

    it('saves both category lists, empty meaning all', async () => {
        open({ staff_properties: ['ZONE'], show_on_resident_portal: true, service_codes: ['graffiti'] });
        const staffGroup = screen.getByRole('group', { name: /record on reports in/i });
        const residentGroup = await waitFor(() => {
            const g = screen.getByRole('group', { name: /show outlines to residents in/i });
            expect(within(staffGroup).getByRole('checkbox', { name: 'Graffiti' })).toBeTruthy();
            return g;
        });
        expect(within(staffGroup).getByText('1 of 3 categories')).toBeTruthy();

        // Staff: back to every category. Residents: Potholes only, found by search.
        fireEvent.click(within(staffGroup).getByRole('radio', { name: 'All categories' }));
        fireEvent.click(within(residentGroup).getByRole('radio', { name: 'Only some' }));
        fireEvent.change(within(residentGroup).getByRole('searchbox'), { target: { value: 'pot' } });
        expect(within(residentGroup).queryByRole('checkbox', { name: 'Streetlights' })).toBeNull();
        fireEvent.click(within(residentGroup).getByRole('checkbox', { name: 'Potholes' }));
        expect(within(residentGroup).getByText('1 of 3 categories')).toBeTruthy();

        fireEvent.click(screen.getByRole('button', { name: /save settings/i }));
        await waitFor(() => expect(api.updateMapLayer).toHaveBeenCalled());
        expect(api.updateMapLayer).toHaveBeenCalledWith(7, expect.objectContaining({
            service_codes: [], resident_service_codes: ['potholes'], show_on_resident_portal: true,
        }));
    });

    it('narrows and counts the staff fields', () => {
        open();
        expect(screen.getByText('0 of 4 selected')).toBeTruthy();
        fireEvent.change(screen.getByRole('searchbox', { name: 'Search fields' }), { target: { value: 'zo' } });
        expect(screen.queryByRole('checkbox', { name: /PAMS_PIN/ })).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Select shown' }));
        expect(screen.getByText('1 of 4 selected')).toBeTruthy();
    });
});
