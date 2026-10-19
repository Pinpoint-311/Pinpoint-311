import { describe, it, expect } from 'vitest';
import {
    CATEGORY_ICONS, categoryIconFor, suggestCategoryIcon, searchCategoryIcons, isDefaultOrUnknownIcon,
} from './categoryIcons';
import { AlertCircle, Trash2 } from 'lucide-react';

describe('suggestCategoryIcon', () => {
    // A real-world category list, as a pilot town set it up.
    const cases: [string, string][] = [
        ['ADA Accessibility Concerns', 'Accessibility'],
        ['General Questions/Other', 'MessageCircleQuestion'],
        ['Animal Concerns (Non-Emergency)', 'PawPrint'],
        ['Street Lighting', 'Lightbulb'],
        ['Code Enforcement', 'Gavel'],
        ['Certificate of Occupancy', 'FileCheck'],
        ['Construction Permit Inquiry', 'HardHat'],
        ['Other Permit Inquiry', 'Stamp'],
        ['Brush Pick-Up', 'Sprout'],
        ['Leaf Pick-Up', 'Leaf'],
        ['Clogged Storm Drains', 'Waves'],
        ['Damaged Street Signs', 'SignpostBig'],
        ['Roadway Flooding (Non-Emergency)', 'CloudRain'],
        ['Recycling', 'Recycle'],
        ['Pothole', 'Construction'],
        ['Snow Removal (Non-Emergency)', 'Snowflake'],
        ['Trash Pick-Up', 'Trash2'],
        ['Bulk Pick-Up', 'Sofa'],
        ['Parks and Playgrounds', 'TreePine'],
        ['Tax Assessment', 'Calculator'],
        ['Tax Collection', 'Receipt'],
        ['Traffic Safety Concerns (Non-Emergency)', 'TrafficCone'],
        ['Water and Sewer Collection (Non-Emergency)', 'Droplet'],
        ['Zoning Permit Inquiry', 'LandPlot'],
        ['Zoning Questions', 'LandPlot'],
    ];
    it.each(cases)('%s -> %s', (name, icon) => {
        expect(suggestCategoryIcon(name)).toBe(icon);
    });

    it('returns null when nothing matches', () => {
        expect(suggestCategoryIcon('Xyzzy')).toBeNull();
    });
});

describe('the registry', () => {
    it('has unique names and a component for each', () => {
        const names = CATEGORY_ICONS.map(d => d.name);
        expect(new Set(names).size).toBe(names.length);
        for (const d of CATEGORY_ICONS) expect(d.icon).toBeTruthy();
    });

    it('still renders names saved by earlier versions', () => {
        expect(categoryIconFor('Trash')).toBe(Trash2);
        expect(categoryIconFor('Spray')).not.toBe(AlertCircle);
        expect(categoryIconFor('nonsense')).toBe(AlertCircle);
        expect(categoryIconFor(undefined)).toBe(AlertCircle);
    });

    it('treats the default and unknown names as needing an icon', () => {
        expect(isDefaultOrUnknownIcon('AlertCircle')).toBe(true);
        expect(isDefaultOrUnknownIcon('nonsense')).toBe(true);
        expect(isDefaultOrUnknownIcon('Snowflake')).toBe(false);
    });

    it('searches by label and keyword', () => {
        expect(searchCategoryIcons('snow').map(d => d.name)).toContain('Snowflake');
        expect(searchCategoryIcons('graffiti').map(d => d.name)).toContain('SprayCan');
    });
});
