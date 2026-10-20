// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { useState } from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Checkbox, CheckboxCard } from './Checkbox';

/**
 * The shared checkbox replaces three looks and two hand-drawn sr-only
 * surrogates. It is restyled, not replaced: these hold it to what a native
 * checkbox gives for free, so the restyling can never cost a keyboard or
 * screen-reader user anything.
 */

afterEach(cleanup);

function Controlled({ onChange }: { onChange?: (v: boolean) => void }) {
    const [on, setOn] = useState(false);
    return (
        <label>
            <Checkbox checked={on} onChange={e => { setOn(e.target.checked); onChange?.(e.target.checked); }} />
            Email me updates
        </label>
    );
}

describe('Checkbox', () => {
    it('is a native checkbox named by its wrapping label', () => {
        render(<Controlled />);
        const box = screen.getByRole('checkbox', { name: 'Email me updates' });
        expect(box.tagName).toBe('INPUT');
        expect((box as HTMLInputElement).type).toBe('checkbox');
    });

    it('is named by htmlFor as well', () => {
        render(<><Checkbox id="cb-x" /><label htmlFor="cb-x">Two-person approval</label></>);
        expect(screen.getByRole('checkbox', { name: 'Two-person approval' })).toBeTruthy();
    });

    it('toggles from the keyboard with Space, and from a click on its label', async () => {
        const user = userEvent.setup();
        const changes: boolean[] = [];
        render(<Controlled onChange={v => changes.push(v)} />);
        const box = screen.getByRole('checkbox') as HTMLInputElement;

        await user.tab();
        expect(document.activeElement).toBe(box);
        await user.keyboard(' ');
        expect(box.checked).toBe(true);

        await user.click(screen.getByText('Email me updates'));
        expect(box.checked).toBe(false);
        expect(changes).toEqual([true, false]);
    });

    it('sets the indeterminate property, which is announced as mixed', () => {
        const { rerender } = render(<Checkbox aria-label="All fields" indeterminate readOnly checked={false} />);
        const box = screen.getByRole('checkbox', { name: 'All fields' }) as HTMLInputElement;
        expect(box.indeterminate).toBe(true);
        rerender(<Checkbox aria-label="All fields" readOnly checked />);
        expect(box.indeterminate).toBe(false);
        expect(box.checked).toBe(true);
    });

    it('keeps the attributes a caller passes: id, name, value, aria-*', () => {
        render(
            <>
                <Checkbox id="c1" name="status" value="open" aria-describedby="hint" aria-label="Open" />
                <p id="hint">Show open requests</p>
            </>,
        );
        const box = screen.getByRole('checkbox', { name: 'Open' }) as HTMLInputElement;
        expect(box.id).toBe('c1');
        expect(box.name).toBe('status');
        expect(box.value).toBe('open');
        expect(box.getAttribute('aria-describedby')).toBe('hint');
    });

    it('marks an error as invalid, unless the caller already said', () => {
        render(<><Checkbox aria-label="A" error /><Checkbox aria-label="B" error aria-invalid={false} /></>);
        expect(screen.getByRole('checkbox', { name: 'A' }).getAttribute('aria-invalid')).toBe('true');
        expect(screen.getByRole('checkbox', { name: 'B' }).getAttribute('aria-invalid')).toBe('false');
    });

    it('cannot be toggled or focused when disabled', async () => {
        const user = userEvent.setup();
        const onChange = vi.fn();
        render(<label><Checkbox disabled onChange={onChange} />Locked</label>);
        await user.click(screen.getByText('Locked'));
        await user.tab();
        expect(onChange).not.toHaveBeenCalled();
        expect(document.activeElement).not.toBe(screen.getByRole('checkbox'));
    });

    it('hides its drawn mark from assistive technology and carries the system focus ring', () => {
        const { container } = render(<Checkbox aria-label="X" />);
        container.querySelectorAll('svg').forEach(svg => expect(svg.getAttribute('aria-hidden')).toBe('true'));
        const cls = screen.getByRole('checkbox').className;
        expect(cls).toContain('focus-visible:ring-[3px]');
        expect(cls).toContain('focus-visible:ring-amber-300');
        expect(cls).toContain('motion-reduce:transition-none');
    });
});

describe('CheckboxCard', () => {
    it('names the box by its title and description, and toggles from anywhere on the card', async () => {
        const user = userEvent.setup();
        function Card() {
            const [on, setOn] = useState(false);
            return <CheckboxCard checked={on} onChange={e => setOn(e.target.checked)} title="Photos" description="Deleted from disk." descriptionId="d1" aria-describedby="d1" />;
        }
        render(<Card />);
        const box = screen.getByRole('checkbox', { name: /Photos/ }) as HTMLInputElement;
        expect(document.getElementById('d1')?.textContent).toBe('Deleted from disk.');
        await user.click(screen.getByText('Deleted from disk.'));
        expect(box.checked).toBe(true);
        box.focus();
        await user.keyboard(' ');
        expect(box.checked).toBe(false);
    });
});

describe('the tick after unchecking', () => {
    afterEach(cleanup);

    it('is not hidden with opacity-0, which index.css reveals inside a focused group', () => {
        // `.group:focus-within .opacity-0 { opacity: 1 !important }` exists so
        // keyboard users can see hover-only buttons. A clicked checkbox keeps
        // focus, so a tick hidden that way stayed visible, half-size, after
        // the box was unchecked.
        const { container } = render(
            <>
                <CheckboxCard title="Email" defaultChecked />
                <Checkbox aria-label="mixed" indeterminate />
            </>,
        );
        const marks = container.querySelectorAll('svg');
        expect(marks.length).toBe(2);
        marks.forEach(mark => expect(mark.classList.contains('opacity-0')).toBe(false));
    });
});
