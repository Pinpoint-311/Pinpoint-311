import { describe, it, expect } from 'vitest';
import { sourceLabel } from './requestSource';

describe('sourceLabel', () => {
    it('labels each intake channel the way the Received by selector does', () => {
        expect(sourceLabel('phone')).toBe('Phone');
        expect(sourceLabel('email')).toBe('Email');
        expect(sourceLabel('walk_in')).toBe('In person');
        expect(sourceLabel('other')).toBe('Other');
    });
    it('calls resident submissions Online and names connector imports', () => {
        expect(sourceLabel('resident_portal')).toBe('Online');
        expect(sourceLabel(undefined)).toBe('Online');
        expect(sourceLabel('integration_arcgis')).toBe('From Arcgis');
    });
});
