import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';

const api = vi.hoisted(() => ({
    inspectArcGis: vi.fn(),
    importArcGis: vi.fn(),
    getArcGisJob: vi.fn(),
    refreshArcGisLayer: vi.fn(),
    checkArcGisLayer: vi.fn(),
    setArcGisSync: vi.fn(),
    getLayerLimits: vi.fn(),
    startLayerUpload: vi.fn(),
    uploadLayerChunk: vi.fn(),
    discardLayerUpload: vi.fn(),
    createPolygonLayer: vi.fn(),
}));
const dialog = vi.hoisted(() => ({ confirm: vi.fn(), alert: vi.fn() }));
vi.mock('../services/api', () => ({ api, default: api }));
vi.mock('./DialogProvider', () => ({ useDialog: () => dialog }));

import { ArcGisImportForm, ArcGisSourcePanel, arcgisSourceLabel, runArcGisJob } from './ArcGisImport';
import AddLayerTypeStep from './AddLayerTypeStep';
import { PolygonLayerUploadForm } from './PolygonLayerManager';

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const LAYER_URL = 'https://gis.example.org/arcgis/rest/services/Parcels/FeatureServer/0';

const parcels = {
    id: 0, name: 'Tax Parcels', url: LAYER_URL, geometry: 'polygon', feature_count: 152000,
    in_area_count: 14000, fields: ['PIN', 'OWNER'], limit: 500000, importable: true, problem: null, warning: null,
};

function renderForm() {
    const onCreated = vi.fn();
    render(<ArcGisImportForm onCancel={() => {}} onCreated={onCreated} />);
    return { onCreated };
}

function pasteAndCheck(url = LAYER_URL) {
    fireEvent.change(screen.getByLabelText(/arcgis link/i), { target: { value: url } });
    fireEvent.click(screen.getByRole('button', { name: /check link/i }));
}

describe('ArcGisImportForm', () => {
    it('starts with only the link: nothing to import yet', () => {
        renderForm();
        expect(screen.getByLabelText(/arcgis link/i)).toBeTruthy();
        expect((screen.getByRole('button', { name: /^import$/i }) as HTMLButtonElement).disabled).toBe(true);
        expect(screen.queryByRole('group', { name: /layer type/i })).toBeNull();
    });

    it('asks for a link before checking', async () => {
        renderForm();
        fireEvent.click(screen.getByRole('button', { name: /check link/i }));
        expect((await screen.findByRole('alert')).textContent).toMatch(/paste an arcgis layer link/i);
        expect(api.inspectArcGis).not.toHaveBeenCalled();
    });

    it('one layer found: picked, named, and the type follows its geometry', async () => {
        api.inspectArcGis.mockResolvedValue({ kind: 'layer', resolved_url: LAYER_URL, layers: [parcels], area: 'Testville', clipped: true });
        renderForm();
        pasteAndCheck();
        const picked = await screen.findByRole('radio', { name: /tax parcels/i });
        expect((picked as HTMLInputElement).checked).toBe(true);
        expect(screen.getByText(/152,000 features, about 14,000 near Testville/)).toBeTruthy();
        const type = screen.getByRole('group', { name: /layer type/i });
        expect(within(type).getByRole('button', { name: /polygons/i }).getAttribute('aria-pressed')).toBe('true');
        expect((within(type).getByRole('button', { name: /points/i }) as HTMLButtonElement).disabled).toBe(true);
        expect((screen.getByLabelText(/layer name/i) as HTMLInputElement).value).toBe('Tax Parcels');
        expect(screen.getByText(/only what is in testville is kept/i)).toBeTruthy();
        expect(api.inspectArcGis).toHaveBeenCalledWith(LAYER_URL, undefined);
    });

    it('a service lists its layers; lines cannot be picked and say why', async () => {
        api.inspectArcGis.mockResolvedValue({
            kind: 'service', resolved_url: LAYER_URL.replace(/\/0$/, ''), area: null, clipped: false, layers: [
                parcels,
                { ...parcels, id: 1, name: 'Hydrants', url: LAYER_URL.replace(/0$/, '1'), geometry: 'point', feature_count: 900, in_area_count: null },
                { ...parcels, id: 2, name: 'Roads', url: LAYER_URL.replace(/0$/, '2'), geometry: 'line', importable: false, problem: "Line layers can't be imported yet. Pinpoint takes point and polygon layers." },
            ],
        });
        renderForm();
        pasteAndCheck();
        expect(await screen.findByText(/3 layers found/i)).toBeTruthy();
        expect((screen.getByRole('radio', { name: /roads/i }) as HTMLInputElement).disabled).toBe(true);
        expect(screen.getByText(/line layers can't be imported yet/i)).toBeTruthy();
        fireEvent.click(screen.getByRole('radio', { name: /hydrants/i }));
        const type = screen.getByRole('group', { name: /layer type/i });
        expect(within(type).getByRole('button', { name: /points/i }).getAttribute('aria-pressed')).toBe('true');
        expect(screen.getByText(/no township boundary is set/i)).toBeTruthy();
    });

    it('a secured service opens the sign-in field, and the token goes with the next check', async () => {
        api.inspectArcGis.mockRejectedValueOnce(new Error('The service needs a sign-in token.'));
        renderForm();
        pasteAndCheck();
        expect((await screen.findByRole('alert')).textContent).toBe('The service needs a sign-in token.');
        const token = screen.getByLabelText(/sign-in token/i) as HTMLInputElement;
        expect(token.type).toBe('password');
        expect(token.closest('details')?.open).toBe(true);
        api.inspectArcGis.mockResolvedValueOnce({ kind: 'layer', resolved_url: LAYER_URL, layers: [parcels], area: null, clipped: false });
        fireEvent.change(token, { target: { value: 'tok-123' } });
        fireEvent.click(screen.getByRole('button', { name: /check link/i }));
        await screen.findByRole('radio', { name: /tax parcels/i });
        expect(api.inspectArcGis).toHaveBeenLastCalledWith(LAYER_URL, 'tok-123');
    });

    it('imports with progress and hands back the layer', async () => {
        api.inspectArcGis.mockResolvedValue({ kind: 'layer', resolved_url: LAYER_URL, layers: [parcels], area: 'Testville', clipped: true });
        api.importArcGis.mockResolvedValue({ job_id: 'j1', kind: 'import', state: 'running', read: 2000, expected: 14000, error: null, result: null });
        const layer = { id: 7, name: 'Tax Parcels' };
        api.getArcGisJob.mockResolvedValue({ job_id: 'j1', kind: 'import', state: 'done', read: 14000, expected: 14000, error: null, result: { layer } });
        const { onCreated } = renderForm();
        pasteAndCheck();
        await screen.findByRole('radio', { name: /tax parcels/i });
        fireEvent.click(screen.getByRole('button', { name: /^import$/i }));
        expect((await screen.findByRole('status')).textContent).toMatch(/2,000 of about 14,000 features read/);
        await waitFor(() => expect(onCreated).toHaveBeenCalledWith(layer, 'polygons'), { timeout: 3000 });
        expect(api.importArcGis).toHaveBeenCalledWith({ url: LAYER_URL, token: undefined, name: 'Tax Parcels', as: 'polygons' });
    });

    it('a failed import shows the plain message and keeps the form', async () => {
        api.inspectArcGis.mockResolvedValue({ kind: 'layer', resolved_url: LAYER_URL, layers: [parcels], area: null, clipped: false });
        api.importArcGis.mockResolvedValue({ job_id: 'j2', kind: 'import', state: 'failed', read: 0, expected: null, error: 'Too many features: 600,000; the limit is 500,000.', result: null });
        const { onCreated } = renderForm();
        pasteAndCheck();
        await screen.findByRole('radio', { name: /tax parcels/i });
        fireEvent.click(screen.getByRole('button', { name: /^import$/i }));
        expect((await screen.findByRole('alert')).textContent).toBe('Too many features: 600,000; the limit is 500,000.');
        expect(onCreated).not.toHaveBeenCalled();
        expect(screen.getByLabelText(/arcgis link/i)).toBeTruthy();
    });
});

describe('runArcGisJob', () => {
    it('polls until the job finishes', async () => {
        api.getArcGisJob
            .mockResolvedValueOnce({ job_id: 'j', state: 'running', read: 5 })
            .mockResolvedValueOnce({ job_id: 'j', state: 'done', read: 9, result: { layer: { id: 1 } } });
        const seen: number[] = [];
        const job = await runArcGisJob(async () => ({ job_id: 'j', state: 'running', read: 0 } as never),
            j => seen.push(j.read), async () => {});
        expect(job.state).toBe('done');
        expect(seen).toEqual([0, 5, 9]);
    });
});

const imported = {
    id: 3, name: 'Tax Parcels', fill_color: '#f59e0b', stroke_color: '#b45309', fill_opacity: 0.1, stroke_width: 1,
    geojson: {}, is_active: true, show_on_resident_portal: false, feature_count: 14000,
    source_url: LAYER_URL, source_synced_at: '2026-10-19T12:00:00Z', source_sync: null, source_sync_status: 'ok',
};

describe('ArcGisSourcePanel', () => {
    it('says where the layer came from and when it was synced', () => {
        render(<ArcGisSourcePanel layer={imported as never} onUpdated={() => {}} />);
        expect(screen.getByText(LAYER_URL)).toBeTruthy();
        expect(screen.getByText(/last synced .*2026 · 14,000 features/i)).toBeTruthy();
        expect(screen.getByText('Up to date')).toBeTruthy();
        expect((screen.getByLabelText(/auto-sync/i) as HTMLSelectElement).value).toBe('off');
        expect(screen.getByText(/auto-sync needs a public service/i)).toBeTruthy();
        expect(arcgisSourceLabel(imported as never)).toMatch(/^From ArcGIS · last synced /);
        expect(arcgisSourceLabel({ source_url: null } as never)).toBeNull();
    });

    it('turning on auto-sync saves it; a secured service says why it cannot', async () => {
        const onUpdated = vi.fn();
        api.setArcGisSync.mockResolvedValueOnce({ ...imported, source_sync: 'daily' });
        render(<ArcGisSourcePanel layer={imported as never} onUpdated={onUpdated} />);
        fireEvent.change(screen.getByLabelText(/auto-sync/i), { target: { value: 'daily' } });
        await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ source_sync: 'daily' })));
        api.setArcGisSync.mockRejectedValueOnce(new Error('Auto-sync needs a public service. For secured services, use Refresh from ArcGIS.'));
        fireEvent.change(screen.getByLabelText(/auto-sync/i), { target: { value: 'weekly' } });
        expect((await screen.findByRole('alert')).textContent).toMatch(/needs a public service/);
    });

    it('refresh asks first, says it replaces the features, and reports before and after', async () => {
        const onUpdated = vi.fn();
        dialog.confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
        const after = { ...imported, feature_count: 14100, import_summary: { clip_message: 'Kept 14,100 of 14,300 features inside Testville.' } };
        api.refreshArcGisLayer.mockResolvedValue({ job_id: 'r', state: 'done', read: 14300, expected: 14000, error: null, result: { layer: after, before: 14000, after: 14100 } });
        render(<ArcGisSourcePanel layer={imported as never} onUpdated={onUpdated} />);
        fireEvent.click(screen.getByRole('button', { name: /refresh from arcgis/i }));
        await waitFor(() => expect(dialog.confirm).toHaveBeenCalledTimes(1));
        expect(dialog.confirm.mock.calls[0][0].message).toMatch(/replaces all 14,000 features/);
        expect(api.refreshArcGisLayer).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: /refresh from arcgis/i }));
        await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(after));
        expect(screen.getByText(/14,000 features before, 14,100 now\. Kept 14,100 of 14,300/)).toBeTruthy();
    });

    it('a held sync says why, and offers Apply anyway or turning sync off', async () => {
        const held = { ...imported, source_sync: 'daily', source_sync_status: 'held',
            source_sync_error: 'The feature count would drop from 14,000 to 9,000 (more than 20%).' };
        dialog.confirm.mockResolvedValue(true);
        api.refreshArcGisLayer.mockResolvedValue({ job_id: 'r', state: 'done', read: 9000, error: null, result: { layer: { ...held, source_sync_status: 'updated' }, before: 14000, after: 9000 } });
        render(<ArcGisSourcePanel layer={held as never} onUpdated={() => {}} />);
        const alert = screen.getByRole('alert');
        expect(alert.textContent).toMatch(/needs review.*drop from 14,000 to 9,000.*keeps its previous features/i);
        expect(screen.getByText('Needs review')).toBeTruthy();
        fireEvent.click(within(alert).getByRole('button', { name: /apply anyway/i }));
        await waitFor(() => expect(api.refreshArcGisLayer).toHaveBeenCalledWith(3, { token: undefined, apply_anyway: true }));
        expect(within(alert).getByRole('button', { name: /turn auto-sync off/i })).toBeTruthy();
    });

    it('Check now reports an unchanged source', async () => {
        api.checkArcGisLayer.mockResolvedValue({ job_id: 'c', state: 'done', read: 0, error: null, result: { layer: imported, sync: { state: 'unchanged' } } });
        render(<ArcGisSourcePanel layer={imported as never} onUpdated={() => {}} />);
        fireEvent.click(screen.getByRole('button', { name: /check now/i }));
        expect(await screen.findByText(/no changes in arcgis since the last sync/i)).toBeTruthy();
    });
});

describe('Add Layer: from a file or from ArcGIS', () => {
    it('offers the ArcGIS import beside the file upload', () => {
        render(<AddLayerTypeStep layerType="" onTypeChange={() => {}} onCancel={() => {}} onPolygonCreated={() => {}}><p>point form</p></AddLayerTypeStep>);
        const file = screen.getByRole('radio', { name: /upload a file/i }) as HTMLInputElement;
        expect(file.checked).toBe(true);
        expect(screen.getByRole('group', { name: /layer type/i })).toBeTruthy();
        fireEvent.click(screen.getByRole('radio', { name: /import from arcgis/i }));
        expect(screen.getByLabelText(/arcgis link/i)).toBeTruthy();
        expect(screen.queryByRole('group', { name: /layer type/i })).toBeNull();
    });
});

describe('the upload help shows the server limits', () => {
    it('reads them from the server', async () => {
        api.getLayerLimits.mockResolvedValue({ max_upload_bytes: 500 * 1048576, max_features: 500000, max_inline_features: 50000, max_inline_bytes: 25 * 1048576, chunk_bytes: 8 * 1048576 });
        render(<PolygonLayerUploadForm onCancel={() => {}} onCreated={() => {}} />);
        expect(await screen.findByText(/up to 500 MB and 500,000 features/)).toBeTruthy();
        expect(screen.queryByText(/100 MB/)).toBeNull();
    });
});
