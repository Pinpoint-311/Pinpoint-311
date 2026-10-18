// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The Photo Redaction card's on-server detectors: the license plate detector
 * select and the face fallback select, each with whether its model file is
 * installed. A model whose file is missing cannot be picked.
 */

const getRedactionDetectors = vi.fn();
const updateRedactionDetectors = vi.fn();
vi.mock('../services/api', () => {
    const api = {
        getRedactionDetectors: (...a: unknown[]) => getRedactionDetectors(...a),
        updateRedactionDetectors: (...a: unknown[]) => updateRedactionDetectors(...a),
    };
    return { default: api, api };
});

import RedactionDetectorsPanel from './RedactionDetectorsPanel';

const model = (present: boolean, error = '') => ({
    file: 'm.onnx', present, loaded: false, error, sha256: present ? 'ab' : '', size_bytes: present ? 1 : 0,
});

function state(over: Record<string, unknown> = {}) {
    return {
        plate_detector: 'yolo', plate_detector_stored: 'auto', face_fallback: 'yunet', face_fallback_stored: 'auto',
        plate_ocr_union: false,
        models: { plate: model(true), face: model(true), models_dir: '/models' },
        ...over,
    };
}

let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

async function render() {
    await act(async () => { root.render(<RedactionDetectorsPanel />); });
    await act(async () => { await Promise.resolve(); });
}

describe('RedactionDetectorsPanel', () => {
    it('shows the selected detectors and that their models are installed', async () => {
        getRedactionDetectors.mockResolvedValue(state());
        await render();
        const plate = host.querySelector<HTMLSelectElement>('#plate-detector')!;
        expect(plate.value).toBe('yolo');
        expect(host.querySelector<HTMLSelectElement>('#face-fallback')!.value).toBe('yunet');
        expect(host.textContent).toContain('License plate detector');
        expect(host.textContent).toContain('Model installed');
        expect([...plate.options].map(o => o.textContent)).toEqual([
            'On-server plate model (recommended)', 'Text recognition', 'Off']);
    });

    it('says the model files are missing and will not offer the model', async () => {
        getRedactionDetectors.mockResolvedValue(state({
            plate_detector: 'ocr', models: { plate: model(false), face: model(false), models_dir: '/models' },
        }));
        await render();
        expect(host.textContent).toContain('Model files missing — see setup');
        const yolo = host.querySelector<HTMLOptionElement>('#plate-detector option[value="yolo"]')!;
        expect(yolo.disabled).toBe(true);
        expect(host.textContent).toContain('/models');
    });

    it('saves a change and shows what the server now reports', async () => {
        getRedactionDetectors.mockResolvedValue(state());
        updateRedactionDetectors.mockResolvedValue(state({ plate_detector: 'ocr' }));
        await render();
        const plate = host.querySelector<HTMLSelectElement>('#plate-detector')!;
        await act(async () => {
            plate.value = 'ocr';
            plate.dispatchEvent(new Event('change', { bubbles: true }));
        });
        expect(updateRedactionDetectors).toHaveBeenCalledWith({ plate_detector: 'ocr' });
        expect(host.querySelector<HTMLSelectElement>('#plate-detector')!.value).toBe('ocr');
    });

    it('reports a model that failed to load', async () => {
        getRedactionDetectors.mockResolvedValue(state({
            models: { plate: model(true, 'bad file'), face: model(true), models_dir: '/models' },
        }));
        await render();
        expect(host.textContent).toContain('Model failed to load');
    });

    it('renders nothing for an older server', async () => {
        getRedactionDetectors.mockRejectedValue(new Error('404'));
        await render();
        expect(host.innerHTML).toBe('');
    });
});
