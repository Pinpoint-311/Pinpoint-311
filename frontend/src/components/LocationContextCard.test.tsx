import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({ getFeatureReports: vi.fn() }));
vi.mock('../services/api', () => ({ api, default: api }));

import LocationContextCard, { LocationContextSection, contextAttributes, featureNoun } from './LocationContextCard';

const parcel = {
    layer_id: 3, layer_name: 'Tax Parcels', feature_id: 91, feature_key: '12-4',
    label: '1 Main St', properties: { PAMS_PIN: '12-4', ZONE: 'R-1', ACRES: 0.25, NOTES: '' },
};

const reports = Array.from({ length: 3 }, (_, i) => ({
    service_request_id: `SR-${i}`, service_name: 'Pothole',
    status: i === 0 ? 'open' : 'closed', requested_datetime: `2026-0${9 - i}-01T00:00:00Z`,
    description: `Report ${i}`,
}));

describe('helpers', () => {
    it('names the feature after its layer', () => {
        expect(featureNoun('Tax Parcels')).toBe('parcel');
        expect(featureNoun('Zoning Districts')).toBe('zone');
        expect(featureNoun('Wards')).toBe('district');
        expect(featureNoun('Flood areas')).toBe('area');
    });
    it('shows every allowlisted field, humanized, and drops empty ones', () => {
        expect(contextAttributes(parcel.properties).map(a => [a.label, a.value])).toEqual([
            ['Pams pin', '12-4'], ['ZONE', 'R-1'], ['ACRES', '0.25'],
        ]);
    });
});

describe('LocationContextCard', () => {
    afterEach(cleanup);

    it('shows the layer, label, allowlisted fields and the reports in the parcel', () => {
        const open = vi.fn();
        render(<LocationContextCard entry={parcel} reports={reports} loading={false} onOpenReport={open} />);
        expect(screen.getByRole('region', { name: /location context: tax parcels/i })).toBeTruthy();
        expect(screen.getByText('1 Main St')).toBeTruthy();
        expect(screen.getByText(/Tax Parcels · ID 12-4/)).toBeTruthy();
        expect(screen.getByText('R-1')).toBeTruthy();
        expect(screen.getByText(/recorded when reported/i)).toBeTruthy();
        expect(screen.getByText(/included on the work order/i)).toBeTruthy();
        expect(screen.getByText(/3 other reports in this parcel/)).toBeTruthy();
        expect(screen.getByText(/1 still open/)).toBeTruthy();
        fireEvent.click(screen.getByText('Report 2'));
        expect(open).toHaveBeenCalledWith('SR-2');
    });

    it('says when there is nothing else in the parcel', () => {
        render(<LocationContextCard entry={parcel} reports={[]} loading={false} onOpenReport={() => {}} />);
        expect(screen.getByText(/no other reports in this parcel/i)).toBeTruthy();
    });

    it('does not print a shape hash as an ID', () => {
        render(<LocationContextCard entry={{ ...parcel, feature_key: 'g:abc123', label: 'g:abc123', properties: {} }}
            reports={[]} loading={false} onOpenReport={() => {}} />);
        expect(screen.queryByText(/ID g:/)).toBeNull();
    });
});

describe('LocationContextSection', () => {
    afterEach(() => { cleanup(); api.getFeatureReports.mockReset(); });

    it('loads each feature history by layer and key, leaving the open report out', async () => {
        api.getFeatureReports.mockResolvedValue(reports);
        const zone = { ...parcel, layer_id: 4, layer_name: 'Zoning', feature_key: 'R-1', label: 'R-1', properties: {} };
        render(<LocationContextSection entries={[parcel, zone]} requestId="SR-9" onOpenReport={() => {}} />);
        await waitFor(() => expect(screen.getAllByText(/3 other reports/)).toHaveLength(2));
        expect(api.getFeatureReports).toHaveBeenCalledWith(3, '12-4', 'SR-9');
        expect(api.getFeatureReports).toHaveBeenCalledWith(4, 'R-1', 'SR-9');
        expect(screen.getAllByRole('region')).toHaveLength(2);
    });

    it('renders nothing for a report without context', () => {
        const { container } = render(<LocationContextSection entries={null} requestId="SR-9" onOpenReport={() => {}} />);
        expect(container.innerHTML).toBe('');
        expect(api.getFeatureReports).not.toHaveBeenCalled();
    });
});
