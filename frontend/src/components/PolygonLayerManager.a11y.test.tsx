// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The polygon layer settings dialog was a wall of bare controls: a radio pair,
 * a cramped scroll box of checkboxes, two native checkboxes for what are
 * on/off settings, an unstyled file input. It is now sections under headings,
 * real switches, and pickers. What this pins down is that nothing in it lost
 * a name on the way, the switches are switches a keyboard can flip, and the
 * order a keyboard walks is the order the sections read in.
 */

const api = vi.hoisted(() => ({
    updateMapLayer: vi.fn(),
    getServices: vi.fn(),
    reuploadLayerFeatures: vi.fn(),
    backfillLayerContext: vi.fn(),
    startLayerUpload: vi.fn(),
    uploadLayerChunk: vi.fn(),
    discardLayerUpload: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));
vi.mock('./DialogProvider', () => ({ useDialog: () => ({ confirm: vi.fn(), alert: vi.fn() }) }));

import { ContextLayerSettingsModal } from './PolygonLayerManager';

const layer = {
    id: 3, name: 'Springfield Parcels', fill_color: '#f59e0b', stroke_color: '#b45309', fill_opacity: 0.1,
    stroke_width: 1, geojson: { type: 'FeatureCollection', features: [] }, is_active: true,
    show_on_resident_portal: false, visible_on_map: true, routing_mode: 'context' as const,
    feature_storage: 'table' as const, feature_id_property: 'PIN', label_property: null,
    staff_properties: ['ZONE'], available_properties: ['PIN', 'ZONE', 'OWNER_NAME'],
    field_flags: { OWNER_NAME: 'owner' as const }, feature_count: 1356,
    features_imported_at: '2026-10-18T12:00:00Z',
};

beforeEach(() => {
    api.getServices.mockResolvedValue([
        { id: 1, service_code: 'potholes', service_name: 'Potholes' },
        { id: 2, service_code: 'streetlights', service_name: 'Streetlights' },
    ]);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const open = () => render(<ContextLayerSettingsModal layer={layer} isOpen onClose={() => {}} onSaved={() => {}} />);

describe('layer settings dialog accessibility', () => {
    it('is named by the layer and described by its one-line summary', () => {
        open();
        const dialog = screen.getByRole('dialog', { name: 'Springfield Parcels' });
        const described = document.getElementById(dialog.getAttribute('aria-describedby') || '');
        expect(described?.textContent).toMatch(/1,356 polygons · imported/);
    });

    it('names every control', async () => {
        open();
        const dialog = screen.getByRole('dialog');
        await waitFor(() => expect(api.getServices).toHaveBeenCalled());
        // Every one of each role, and every one of each role with a non-empty
        // accessible name, are the same elements.
        let total = 0;
        for (const role of ['button', 'checkbox', 'radio', 'switch', 'searchbox', 'combobox'] as const) {
            const all = within(dialog).queryAllByRole(role);
            expect(within(dialog).queryAllByRole(role, { name: /\S/ }), role).toEqual(all);
            total += all.length;
        }
        expect(total).toBeGreaterThan(10);
        expect(dialog.querySelector('input[type="file"]')?.getAttribute('aria-label')).toBe('Replacement GeoJSON file');
    });

    it('reads in section order, and a keyboard walks it in the same order', () => {
        open();
        const headings = screen.getAllByRole('heading', { level: 3 }).map(h => h.textContent);
        expect(headings).toEqual(['Purpose', 'Identify features', 'What staff see', 'Visibility', 'Categories', 'Data']);
        // Nothing has a positive tabindex to pull the walk out of reading order.
        expect(screen.getByRole('dialog').querySelectorAll('[tabindex]:not([tabindex="-1"]):not([tabindex="0"])').length).toBe(0);
    });

    it('has real switches a keyboard can flip, with the reason a disabled one is off', async () => {
        const user = userEvent.setup();
        open();
        const staffMap = screen.getByRole('switch', { name: /show outlines on the staff map/i });
        expect(staffMap.getAttribute('aria-checked')).toBe('true');
        staffMap.focus();
        await user.keyboard(' ');
        expect(staffMap.getAttribute('aria-checked')).toBe('false');

        const portal = screen.getByRole('switch', { name: /show on the resident portal/i });
        expect(portal.hasAttribute('disabled')).toBe(false);
        const help = document.getElementById(portal.getAttribute('aria-describedby') || '');
        expect(help?.textContent).toMatch(/shapes only/i);

        // Choosing an owner field turns it off, and the description says why.
        await user.click(screen.getByRole('checkbox', { name: /OWNER_NAME/ }));
        expect(portal.hasAttribute('disabled')).toBe(true);
        expect(help?.textContent).toMatch(/owner details are among the staff fields/i);
    });

    it('keeps the purpose a radio group named by its heading', () => {
        open();
        const group = screen.getByRole('radiogroup', { name: 'Purpose' });
        const radios = within(group).getAllByRole('radio');
        expect(radios).toEqual([
            within(group).getByRole('radio', { name: /^Location context/ }),
            within(group).getByRole('radio', { name: /^Display only/ }),
        ]);
    });
});
