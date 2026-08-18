// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import SecretField from './SecretField';

/**
 * Every credential on Setup & Integrations is one of these, and every one of
 * them reached a screen reader with no name at all: the <label> pointed at
 * nothing, the <input> had no id and no aria-label, and the label did not wrap
 * the box. "Edit text, blank" -- thirty times down the page.
 *
 * The reveal toggle was worse than unnamed, it was unreachable: tabIndex={-1}
 * took the show/hide button out of the tab order, and that button is the entire
 * reason the field exists in this shape -- it is how a clerk eyeballs a pasted
 * key before saving it. A keyboard-only clerk could not verify a single one.
 */

function Harness({ initial = '', ...props }: any) {
    const [value, setValue] = useState(initial);
    return (
        <div>
            <button>before</button>
            <SecretField label="API Key" value={value} onChange={setValue} secret {...props} />
            <button>after</button>
        </div>
    );
}

/** The reveal button is named "Show API Key" too, so pin queries to the input. */
const textOf = (ids: string | null) => (ids || '')
    .split(/\s+/).filter(Boolean)
    .map(id => document.getElementById(id)?.textContent || '')
    .join(' ');

afterEach(cleanup);

describe('a credential field', () => {
    it('is named by its visible label', () => {
        render(<Harness />);
        // Would throw if the label were still unassociated.
        expect(screen.getByLabelText(/API Key/i, { selector: 'input' })).toBeTruthy();
    });

    it('puts the show/hide toggle in the tab order, right after the box', async () => {
        const user = userEvent.setup();
        render(<Harness />);

        const box = screen.getByLabelText(/API Key/i, { selector: 'input' });
        box.focus();
        await user.tab();

        const reveal = screen.getByRole('button', { name: /show API Key/i });
        expect(document.activeElement).toBe(reveal);
    });

    it('reveals and re-hides the value from the keyboard, and says which state it is in', async () => {
        const user = userEvent.setup();
        render(<Harness initial="sk-live-123" />);

        const box = screen.getByLabelText(/API Key/i, { selector: 'input' }) as HTMLInputElement;
        expect(box.type).toBe('password');

        const reveal = screen.getByRole('button', { name: /show API Key/i });
        reveal.focus();
        await user.keyboard('{Enter}');

        expect((screen.getByLabelText(/API Key/i, { selector: 'input' }) as HTMLInputElement).type).toBe('text');
        const hide = screen.getByRole('button', { name: /hide API Key/i });
        expect(hide.getAttribute('aria-pressed')).toBe('true');

        await user.keyboard(' ');
        expect((screen.getByLabelText(/API Key/i, { selector: 'input' }) as HTMLInputElement).type).toBe('password');
    });

    it('links its help text to the box instead of leaving it floating below', () => {
        render(<Harness help="Found in the provider console under Credentials." />);

        const box = screen.getByLabelText(/API Key/i, { selector: 'input' });
        expect(textOf(box.getAttribute('aria-describedby'))).toMatch(/provider console/i);
    });

    it('reports a mangled paste on the field itself, not just as coloured text', async () => {
        const user = userEvent.setup();
        render(<Harness />);

        const box = screen.getByLabelText(/API Key/i, { selector: 'input' });
        await user.click(box);
        await user.paste('"sk-live-123"');

        expect(box.getAttribute('aria-invalid')).toBe('true');
        expect(textOf(box.getAttribute('aria-describedby'))).toMatch(/wrapped in quotes/i);
    });

    it('keeps the "leave blank to keep" instruction outside the placeholder', () => {
        // The placeholder disappears on the first keystroke and is not a label,
        // so it cannot be the only place an instruction lives (WCAG 3.3.2).
        render(<Harness savedHint />);

        const box = screen.getByLabelText(/API Key/i, { selector: 'input' });
        expect(textOf(box.getAttribute('aria-describedby'))).toMatch(/leave this blank to keep it/i);
    });
});
