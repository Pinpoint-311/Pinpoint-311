import { describe, it, expect } from 'vitest';

import type { ServiceDefinition } from '../types';
import {
    agencyRoads, cloneAgency, combinedRoadList, parseAgencyFile, parseRoadEntry, roadLabel, savedAgencies,
} from './agencyLibrary';

const penndot = { name: 'PennDOT', phone: '555-0100', email: 'a@dot.example', url: '', message: 'State road.', road_list: 'Route 1, Route 130' };
const county = { name: 'County DPW', phone: '555-0200', email: '', url: '', message: '', road_list: 'Cranbury Rd' };

const svc = (id: number, name: string, agencies: object[]): ServiceDefinition => ({
    id, service_code: `c${id}`, service_name: name, description: null, icon: 'AlertCircle',
    is_active: true, display_order: id, departments: [], routing_mode: 'road_based',
    routing_config: { third_party_contacts: agencies },
} as unknown as ServiceDefinition);

describe('savedAgencies', () => {
    it('offers agencies from other categories, not the one being edited', () => {
        const services = [svc(1, 'Potholes', [penndot]), svc(2, 'Signs', [county])];
        const saved = savedAgencies(services, 2);
        expect(saved.map(s => s.agency.name)).toEqual(['PennDOT']);
        expect(saved[0].roads).toEqual(['Route 1', 'Route 130']);
        expect(saved[0].usedBy).toEqual(['Potholes']);
    });

    it('collapses the same agency on several categories into one entry', () => {
        const services = [svc(1, 'Potholes', [penndot]), svc(2, 'Signs', [{ ...penndot }]), svc(3, 'Drains', [])];
        const saved = savedAgencies(services, 3);
        expect(saved).toHaveLength(1);
        expect(saved[0].usedBy).toEqual(['Potholes', 'Signs']);
    });

    it('keeps the same name with different roads apart', () => {
        const services = [svc(1, 'Potholes', [penndot]), svc(2, 'Signs', [{ ...penndot, road_list: 'Route 1' }])];
        expect(savedAgencies(services)).toHaveLength(2);
    });

    it('skips unnamed agency cards', () => {
        expect(savedAgencies([svc(1, 'Potholes', [{ name: '  ', road_list: 'Main St' }])])).toEqual([]);
    });
});

describe('cloneAgency', () => {
    it('is a deep copy: editing the copy leaves the source alone', () => {
        const source = { ...penndot, contacts: [{ name: 'Desk', phone: '1' }] };
        const copy = cloneAgency(source) as typeof source;
        expect(copy).not.toBe(source);
        expect(copy.road_list).toBe('Route 1, Route 130');
        copy.name = 'Changed';
        copy.road_list = 'Route 9';
        copy.contacts[0].phone = '2';
        expect(source.name).toBe('PennDOT');
        expect(source.road_list).toBe('Route 1, Route 130');
        expect(source.contacts[0].phone).toBe('1');
    });

    it('carries roads as road_list only, so editing the list cannot leave a stale copy', () => {
        const copy = cloneAgency({ name: 'X', roads: ['A Rd', 'B Rd'] });
        expect(copy.road_list).toBe('A Rd, B Rd');
        expect(copy.roads).toBeUndefined();
    });
});

describe('road entries with limits', () => {
    it('reads "Name (A to B)" and writes a structured entry the same way', () => {
        expect(parseRoadEntry('Oak Road (Elm Street to Route 10)'))
            .toEqual({ name: 'Oak Road', from: 'Elm Street', to: 'Route 10' });
        expect(parseRoadEntry('Route 9')).toEqual({ name: 'Route 9', from: null, to: null });
        expect(roadLabel({ name: 'Example Road A', from_street: 'Elm St', to_street: 'Route 10' }))
            .toBe('Example Road A (Elm St to Route 10)');
    });

    it('keeps a limited road as one entry in the comma-separated list', () => {
        expect(agencyRoads({ road_list: 'Oak Road (Elm Street to Route 10), Route 9' }))
            .toEqual(['Oak Road (Elm Street to Route 10)', 'Route 9']);
        expect(combinedRoadList([penndot, county])).toBe('Route 1, Route 130, Cranbury Rd');
    });
});

describe('parseAgencyFile', () => {
    it('reads the import format', () => {
        const file = JSON.stringify({
            format: 'pinpoint311.agencies', version: 1, title: 'Springfield: county and state roads',
            agencies: [
                { name: 'County Road Department', phone: '555-0300', roads: ['Example Road A', 'Example Road B (First Street to Route 10)'] },
                { name: 'State Highway Agency', roads: ['Route 10', 'Route 20'] },
            ],
        });
        const agencies = parseAgencyFile(file);
        expect(agencies.map(a => a.name)).toEqual(['County Road Department', 'State Highway Agency']);
        expect(agencies[0].phone).toBe('555-0300');
        expect(agencyRoads(agencies[0])).toEqual(['Example Road A', 'Example Road B (First Street to Route 10)']);
        expect(agencyRoads(agencies[1])).toEqual(['Route 10', 'Route 20']);
    });

    it('accepts a bare list and structured road entries', () => {
        const [a] = parseAgencyFile(JSON.stringify([{ name: 'County', roads: [{ name: 'Oak Rd', from_street: 'A St', to_street: 'B St' }] }]));
        expect(a.road_list).toBe('Oak Rd (A St to B St)');
    });

    it('says what is wrong with a bad file', () => {
        expect(() => parseAgencyFile('not json')).toThrow(/not valid JSON/);
        expect(() => parseAgencyFile('{"agencies": []}')).toThrow(/No agencies/);
        expect(() => parseAgencyFile('{"agencies": [{"roads": []}]}')).toThrow(/no name/);
    });
});
