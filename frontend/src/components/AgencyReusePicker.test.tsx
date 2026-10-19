import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';

const dialog = vi.hoisted(() => ({ confirm: vi.fn(), alert: vi.fn() }));
vi.mock('./DialogProvider', () => ({ useDialog: () => dialog }));
const api = vi.hoisted(() => ({ updateService: vi.fn() }));
vi.mock('../services/api', () => ({ api, default: api }));

import AgencyReusePicker from './AgencyReusePicker';
import type { RoutingContact, ServiceDefinition } from '../types';

const penndot = { name: 'PennDOT', phone: '555-0100', email: '', url: '', message: '', road_list: 'Route 1, Route 130' };
const county = { name: 'County DPW', phone: '555-0200', email: '', url: '', message: '', road_list: 'Cranbury Rd' };

const svc = (id: number, name: string, agencies: RoutingContact[]): ServiceDefinition => ({
    id, service_code: `c${id}`, service_name: name, description: null, icon: 'AlertCircle',
    is_active: true, display_order: id, departments: [], routing_mode: 'road_based',
    routing_config: { third_party_contacts: agencies },
} as unknown as ServiceDefinition);

const services = [svc(1, 'Potholes', [penndot, county]), svc(2, 'Street Signs', [])];

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const select = () => screen.getByLabelText('Add a saved agency') as HTMLSelectElement;

describe('AgencyReusePicker', () => {
    it('lists agencies saved on other categories with their road counts', () => {
        render(<AgencyReusePicker services={services} currentServiceId={2} currentAgencies={[]} onApply={() => {}} />);
        const labels = Array.from(select().options).map(o => o.textContent);
        expect(labels).toContain('County DPW: 1 road (on Potholes)');
        expect(labels).toContain('PennDOT: 2 roads (on Potholes)');
    });

    it('applies a deep copy of the chosen agency and its roads', () => {
        const onApply = vi.fn();
        render(<AgencyReusePicker services={services} currentServiceId={2} currentAgencies={[]} onApply={onApply} />);
        const option = Array.from(select().options).find(o => o.textContent?.startsWith('PennDOT'))!;
        fireEvent.change(select(), { target: { value: option.value } });
        expect(screen.getByLabelText('Roads for PennDOT').textContent).toContain('Route 130');
        fireEvent.click(screen.getByRole('button', { name: /apply to this category/i }));

        expect(onApply).toHaveBeenCalledTimes(1);
        const [[applied]] = onApply.mock.calls;
        expect(applied).toHaveLength(1);
        expect(applied[0]).toMatchObject({ name: 'PennDOT', phone: '555-0100', road_list: 'Route 1, Route 130' });
        // A copy, not the source category's object: editing it cannot reach Potholes.
        expect(applied[0]).not.toBe(penndot);
        applied[0].road_list = 'Route 9';
        expect(penndot.road_list).toBe('Route 1, Route 130');
        expect(screen.getByRole('status').textContent).toMatch(/separate copy/);
    });

    it('does not save anything itself: the category save (which is audited) does', () => {
        render(<AgencyReusePicker services={services} currentServiceId={2} currentAgencies={[]} onApply={() => {}} />);
        const option = Array.from(select().options).find(o => o.textContent?.startsWith('PennDOT'))!;
        fireEvent.change(select(), { target: { value: option.value } });
        fireEvent.click(screen.getByRole('button', { name: /apply to this category/i }));
        expect(api.updateService).not.toHaveBeenCalled();
        expect(screen.getByRole('status').textContent).toMatch(/Save to keep it/);
    });

    it('will not add an agency this category already has', () => {
        render(<AgencyReusePicker services={services} currentServiceId={2} currentAgencies={[{ name: 'pennDOT' }]} onApply={() => {}} />);
        const option = Array.from(select().options).find(o => o.textContent?.startsWith('PennDOT'))!;
        expect(option.disabled).toBe(true);
        expect(option.textContent).toMatch(/already on this category/);
    });

    it('says so when there is nothing to reuse yet', () => {
        render(<AgencyReusePicker services={[svc(2, 'Signs', [])]} currentServiceId={2} currentAgencies={[]} onApply={() => {}} />);
        expect(select().disabled).toBe(true);
        expect(select().options[0].textContent).toMatch(/No agencies on other categories/);
    });

    it('imports agencies from a file after confirming, skipping ones already here', async () => {
        dialog.confirm.mockResolvedValue(true);
        const onApply = vi.fn();
        render(<AgencyReusePicker services={services} currentServiceId={2} currentAgencies={[{ name: 'County' }]} onApply={onApply} />);
        const file = new File([JSON.stringify({
            format: 'pinpoint311.agencies',
            agencies: [
                { name: 'Springfield County', roads: ['Elm Street', 'Oak Road (Elm Street to Route 10)'] },
                { name: 'County', roads: ['Oak Rd'] },
            ],
        })], 'set.json', { type: 'application/json' });
        fireEvent.change(screen.getByTestId('agency-file-input'), { target: { files: [file] } });

        await waitFor(() => expect(onApply).toHaveBeenCalled());
        expect(dialog.confirm.mock.calls[0][0].message).toMatch(/Springfield County \(2 roads\)/);
        expect(dialog.confirm.mock.calls[0][0].message).toMatch(/skipped: County/);
        expect(onApply.mock.calls[0][0].map((a: RoutingContact) => a.name)).toEqual(['Springfield County']);
        expect(onApply.mock.calls[0][0][0].road_list).toBe('Elm Street, Oak Road (Elm Street to Route 10)');
    });

    it('shows why a file was refused', async () => {
        render(<AgencyReusePicker services={services} currentServiceId={2} currentAgencies={[]} onApply={() => {}} />);
        const file = new File(['nope'], 'bad.json', { type: 'application/json' });
        fireEvent.change(screen.getByTestId('agency-file-input'), { target: { files: [file] } });
        expect((await screen.findByRole('alert')).textContent).toMatch(/not valid JSON/);
        expect(dialog.confirm).not.toHaveBeenCalled();
    });
});
