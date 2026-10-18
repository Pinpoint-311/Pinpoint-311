import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({
    startLayerUpload: vi.fn(),
    uploadLayerChunk: vi.fn(),
    discardLayerUpload: vi.fn(),
    createPolygonLayer: vi.fn(),
    reuploadLayerFeatures: vi.fn(),
    backfillLayerContext: vi.fn(),
    updateMapLayer: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));
const dialog = vi.hoisted(() => ({ confirm: vi.fn(), alert: vi.fn() }));
vi.mock('./DialogProvider', () => ({ useDialog: () => dialog }));

import { ContextLayerSettingsModal, MAX_LAYER_UPLOAD_BYTES, uploadInChunks } from './PolygonLayerManager';

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
        api.startLayerUpload.mockResolvedValue({ upload_id: 'u1', chunk_bytes: 4, max_bytes: MAX_LAYER_UPLOAD_BYTES });
        api.uploadLayerChunk.mockResolvedValue({});
        const id = await uploadInChunks(new Blob(['0123456789']));
        expect(id).toBe('u1');
        expect(api.startLayerUpload).toHaveBeenCalledWith(10);
        expect(api.uploadLayerChunk.mock.calls.map(c => [c[1], (c[2] as Blob).size])).toEqual([[0, 4], [1, 4], [2, 2]]);
    });

    it('discards a half-finished upload', async () => {
        api.startLayerUpload.mockResolvedValue({ upload_id: 'u2', chunk_bytes: 4, max_bytes: 1 });
        api.uploadLayerChunk.mockRejectedValueOnce(new Error('network'));
        api.discardLayerUpload.mockResolvedValue(undefined);
        await expect(uploadInChunks(new Blob(['0123456789']))).rejects.toThrow('network');
        expect(api.discardLayerUpload).toHaveBeenCalledWith('u2');
    });

    it('refuses a file over the limit before sending anything', async () => {
        const big = { size: MAX_LAYER_UPLOAD_BYTES + 1, slice: () => new Blob() } as unknown as Blob;
        await expect(uploadInChunks(big)).rejects.toThrow(/100 MB/);
        expect(api.startLayerUpload).not.toHaveBeenCalled();
    });
});

describe('ContextLayerSettingsModal', () => {
    beforeEach(() => { api.updateMapLayer.mockImplementation(async (_id, body) => ({ ...layer, ...body, warnings: [] })); });
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
        const portal = () => screen.getByRole('checkbox', { name: /show on the resident portal/i }) as HTMLInputElement;
        expect(portal().disabled).toBe(true);
        expect(screen.getByText(/choose the fields staff see first/i)).toBeTruthy();
        fireEvent.click(screen.getByRole('checkbox', { name: /ZONE/ }));
        expect(portal().disabled).toBe(false);
        fireEvent.click(screen.getByRole('checkbox', { name: /OWNER_NAME/ }));
        expect(portal().disabled).toBe(true);
        expect(screen.getByText(/owner details \(OWNER_NAME\)/i)).toBeTruthy();
    });

    it('saves the purpose, fields and portal choice', async () => {
        const saved = vi.fn();
        render(<ContextLayerSettingsModal layer={layer} isOpen onClose={() => {}} onSaved={saved} />);
        fireEvent.click(screen.getByRole('checkbox', { name: /PAMS_PIN/ }));
        fireEvent.click(screen.getByRole('checkbox', { name: /ZONE/ }));
        fireEvent.change(screen.getByLabelText('Label field'), { target: { value: 'ST_NAME' } });
        fireEvent.click(screen.getByRole('checkbox', { name: /show on the resident portal/i }));
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
});
