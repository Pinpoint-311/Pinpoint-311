import { describe, it, expect, vi, afterEach } from 'vitest';
import { useState } from 'react';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({
    startLayerUpload: vi.fn(),
    uploadLayerChunk: vi.fn(),
    discardLayerUpload: vi.fn(),
    createPolygonLayer: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));
vi.mock('./DialogProvider', () => ({ useDialog: () => ({ confirm: vi.fn(), alert: vi.fn() }) }));

import AddLayerTypeStep, { type NewLayerType } from './AddLayerTypeStep';
import ADMIN_CONSOLE_SOURCE from '../pages/AdminConsole.tsx?raw';

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function Host({ onPolygonCreated = () => {}, editing = false }: { onPolygonCreated?: (l: unknown) => void; editing?: boolean }) {
    const [type, setType] = useState<NewLayerType>(editing ? 'point' : '');
    return (
        <AddLayerTypeStep
            editing={editing}
            layerType={type}
            onTypeChange={setType}
            onCancel={() => {}}
            onPolygonCreated={onPolygonCreated}
        >
            <p>point form</p>
        </AddLayerTypeStep>
    );
}

describe('Add Layer: one entry, two kinds of layer', () => {
    it('offers Points and Polygons side by side, nothing else until one is chosen', () => {
        render(<Host />);
        const group = screen.getByRole('group', { name: /layer type/i });
        const choices = Array.from(group.querySelectorAll('button')).map(b => b.querySelector('.font-semibold')?.textContent);
        expect(choices).toEqual(['Points', 'Polygons']);
        expect(screen.queryByText('point form')).toBeNull();
        expect(screen.queryByLabelText('GeoJSON file')).toBeNull();
    });

    it('Points continues into the point form', () => {
        render(<Host />);
        fireEvent.click(screen.getByRole('button', { name: /points/i }));
        expect(screen.getByRole('button', { name: /points/i }).getAttribute('aria-pressed')).toBe('true');
        expect(screen.getByText('point form')).toBeTruthy();
        expect(screen.queryByLabelText('GeoJSON file')).toBeNull();
    });

    it('Polygons continues into the chunked upload and hands back the new layer', async () => {
        const created = { id: 9, name: 'Tax Parcels' };
        api.startLayerUpload.mockResolvedValue({ upload_id: 'u1', chunk_bytes: 1024, max_bytes: 1 });
        api.uploadLayerChunk.mockResolvedValue({});
        api.createPolygonLayer.mockResolvedValue(created);
        const onCreated = vi.fn();
        render(<Host onPolygonCreated={onCreated} />);

        fireEvent.click(screen.getByRole('button', { name: /polygons/i }));
        expect(screen.queryByText('point form')).toBeNull();
        fireEvent.change(screen.getByLabelText(/layer name/i), { target: { value: 'Tax Parcels' } });
        const file = new File(['{"type":"FeatureCollection","features":[]}'], 'parcels.geojson');
        fireEvent.change(screen.getByLabelText('GeoJSON file'), { target: { files: [file] } });
        fireEvent.click(screen.getByRole('button', { name: /upload and create/i }));

        await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
        expect(api.createPolygonLayer).toHaveBeenCalledWith(expect.objectContaining({
            name: 'Tax Parcels', upload_id: 'u1', routing_mode: 'context',
        }));
    });

    it('editing an existing layer skips the type step', () => {
        render(<Host editing />);
        expect(screen.queryByRole('group', { name: /layer type/i })).toBeNull();
        expect(screen.getByText('point form')).toBeTruthy();
    });

    it('the console has no separate polygon button any more', () => {
        expect(ADMIN_CONSOLE_SOURCE).not.toMatch(/Add Polygon Layer/);
        expect(ADMIN_CONSOLE_SOURCE).not.toMatch(/PolygonLayerUploadModal/);
        expect(ADMIN_CONSOLE_SOURCE).toMatch(/<AddLayerTypeStep/);
    });
});
