import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useState } from 'react';
import { CategoryScopePicker, categoryScopeSummary } from './CategoryScopePicker';

const services = [
    { service_code: 'potholes', service_name: 'Potholes' },
    { service_code: 'streetlights', service_name: 'Streetlights' },
    { service_code: 'graffiti', service_name: 'Graffiti' },
];

function Harness({ initial = [] as string[], onChange = (_: string[]) => {} }) {
    const [value, setValue] = useState(initial);
    return (
        <CategoryScopePicker label="Show for categories" services={services} value={value}
            onChange={codes => { setValue(codes); onChange(codes); }} />
    );
}

afterEach(cleanup);

describe('categoryScopeSummary', () => {
    it('reads empty as every category and counts the rest', () => {
        expect(categoryScopeSummary([], services)).toBe('All categories');
        expect(categoryScopeSummary(['potholes'], services)).toBe('1 of 3 categories');
        // A category since switched off is not counted as one of the known.
        expect(categoryScopeSummary(['potholes', 'retired'], services)).toBe('1 of 3 categories');
    });
});

describe('CategoryScopePicker', () => {
    it('starts on all categories, with no list to tick', () => {
        render(<Harness />);
        expect(screen.getByRole('radio', { name: 'All categories' })).toHaveProperty('checked', true);
        expect(screen.queryByRole('checkbox')).toBeNull();
        expect(screen.getByText('All categories', { selector: 'p' })).toBeTruthy();
    });

    it('searches, selects what is shown, and goes back to all as an empty list', () => {
        const changed = vi.fn();
        render(<Harness onChange={changed} />);
        fireEvent.click(screen.getByRole('radio', { name: 'Only some' }));
        expect(screen.getByText(/none ticked yet: saves as all categories/i)).toBeTruthy();
        fireEvent.change(screen.getByRole('searchbox', { name: /search categories/i }), { target: { value: 'light' } });
        expect(screen.getAllByRole('checkbox').map(b => b.closest('label')?.textContent))
            .toEqual(['Streetlights']);
        fireEvent.click(screen.getByRole('button', { name: 'Select shown' }));
        expect(changed).toHaveBeenLastCalledWith(['streetlights']);
        expect(screen.getByText('1 of 3 categories')).toBeTruthy();
        fireEvent.click(screen.getByRole('radio', { name: 'All categories' }));
        expect(changed).toHaveBeenLastCalledWith([]);
    });

    it('keeps codes it cannot show when ticking others', () => {
        const changed = vi.fn();
        render(<Harness initial={['retired']} onChange={changed} />);
        fireEvent.click(screen.getByRole('checkbox', { name: 'Graffiti' }));
        expect(changed).toHaveBeenLastCalledWith(['retired', 'graffiti']);
    });

    it('says why it is disabled', () => {
        render(<CategoryScopePicker label="Show outlines to residents in" description="Who sees the outlines."
            services={services} value={[]} onChange={() => {}} disabled disabledReason="Turn on the portal first." />);
        const group = screen.getByRole('group', { name: 'Show outlines to residents in' }) as HTMLFieldSetElement;
        expect(group.disabled).toBe(true);
        expect(group.getAttribute('aria-describedby')).toBeTruthy();
        expect(screen.getByText('Turn on the portal first.')).toBeTruthy();
        expect(screen.queryByText('Who sees the outlines.')).toBeNull();
    });
});
