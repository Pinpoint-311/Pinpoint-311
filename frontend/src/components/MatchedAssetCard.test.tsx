import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import MatchedAssetCard, { assetAttributes, assetTitle, humanizeKey } from './MatchedAssetCard';

describe('assetAttributes', () => {
    it('shows every field the GeoJSON carries, numbers included', () => {
        const attrs = assetAttributes({
            asset_id: 'H-0412', OBJECTID: 7, install_year: 1987, Material: 'Ductile iron',
            pressureZone: 'North', in_service: true, notes: '', owner: null,
        });
        expect(attrs.map(a => a.label)).toEqual(['Install year', 'Material', 'Pressure zone', 'In service']);
        // A year is a number; the old filter dropped it as "probably an ID".
        expect(attrs[0].value).toBe('1987');
        expect(attrs[3].value).toBe('Yes');
    });

    it('has no cap: a wide layer shows all of its fields', () => {
        const props = Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`field_${i}`, `v${i}`]));
        expect(assetAttributes(props)).toHaveLength(20);
    });
});

describe('labels', () => {
    it('humanizes keys', () => {
        expect(humanizeKey('INSTALL_YEAR')).toBe('Install year');
        expect(humanizeKey('lastInspected')).toBe('Last inspected');
    });
    it('prefers a name, then type + ID', () => {
        expect(assetTitle({ properties: { name: 'Bay Ave light' }, asset_id: 'SL-1' })).toBe('Bay Ave light');
        expect(assetTitle({ asset_type: 'Hydrant', asset_id: 'H-0412' })).toBe('Hydrant H-0412');
    });
});

describe('MatchedAssetCard', () => {
    afterEach(cleanup);
    const reports = Array.from({ length: 8 }, (_, i) => ({
        service_request_id: `SR-${i}`, service_name: 'Hydrant leak',
        status: i === 0 ? 'open' : 'closed', requested_datetime: `2026-0${9 - Math.min(i, 8)}-01T00:00:00Z`,
        description: `Report ${i}`,
    }));

    it('lists the asset history and opens a report on click', () => {
        const open = vi.fn();
        render(<MatchedAssetCard asset={{ layer_name: 'Hydrants', asset_id: 'H-0412' }} reports={reports} loading={false} onOpenReport={open} />);
        expect(screen.getByText(/8 other reports/)).toBeTruthy();
        expect(screen.getByText(/1 still open/)).toBeTruthy();
        expect(screen.getAllByRole('listitem')).toHaveLength(6);
        fireEvent.click(screen.getByRole('button', { name: /show all 8 reports/i }));
        expect(screen.getAllByRole('listitem')).toHaveLength(8);
        fireEvent.click(screen.getByText('Report 3'));
        expect(open).toHaveBeenCalledWith('SR-3');
    });

    it('says how the asset was attached, not a distance', () => {
        render(<MatchedAssetCard asset={{ layer_name: 'Hydrants', asset_id: 'H-1' }} reports={[]} loading={false} onOpenReport={() => {}} />);
        expect(screen.getByText(/selected on the map when reported/i)).toBeTruthy();
        expect(screen.getByText(/included on the work order/i)).toBeTruthy();
        expect(screen.queryByText(/away/)).toBeNull();
        expect(screen.getByText(/no other reports on this asset/i)).toBeTruthy();
    });
});
