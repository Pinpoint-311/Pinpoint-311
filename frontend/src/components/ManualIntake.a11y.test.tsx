// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The call-taker's repro: pick up the phone, press "Log request" before the
 * category is set, and the form did nothing anybody could perceive -- the
 * submit buttons were `disabled` until the form was already valid, so the one
 * control that would have explained the problem could not be reached or
 * pressed, and the message it would have shown was a plain div with no role.
 *
 * And the category list, the only required field with no typing in it, was
 * mouse-only: a `<ul role="listbox">` full of `<li><button>`, no arrow keys, no
 * Escape, no aria-activedescendant.
 *
 * The contract now: every field has a real <label for>, a failed submit
 * announces itself and puts focus on the field at fault with the message tied
 * to it, and the category combobox is fully operable from the keyboard.
 */

const created = {
    service_request_id: 'REQ-4242',
    service_code: 'pothole',
    service_name: 'Pothole',
    status: 'open',
    description: 'Deep pothole near the crosswalk',
};

const createManualIntake = vi.fn().mockResolvedValue(created);

vi.mock('../services/api', () => {
    const api = {
        createManualIntake: (...args: any[]) => createManualIntake(...args),
        getMapsConfig: vi.fn().mockResolvedValue({}),
        getMapLayers: vi.fn().mockResolvedValue([]),
    };
    return { api, default: api };
});

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { modules: {} } }),
}));

// The map picker is not what is under test, and it never renders here anyway:
// the mocked maps config carries no provider key, so the form falls back to a
// plain address field.
vi.mock('./LocationPicker', () => ({ default: () => null }));

import ManualIntake from './ManualIntake';
import { AccessibilityProvider } from '../context/AccessibilityContext';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}

const services = [
    { service_code: 'pothole', service_name: 'Pothole', is_active: true },
    { service_code: 'streetlight', service_name: 'Streetlight Out', is_active: true },
    { service_code: 'graffiti', service_name: 'Graffiti', is_active: true },
] as any;

const onCreated = vi.fn();
const onClose = vi.fn();

async function open() {
    render(
        <AccessibilityProvider>
            <ManualIntake isOpen onClose={onClose} services={services} onCreated={onCreated} />
        </AccessibilityProvider>,
    );
    // The dialog focuses the description on open, on a timer. Waiting for that
    // to land keeps a stray late focus out of the assertions below.
    const description = await screen.findByLabelText(/what is the caller reporting/i);
    await waitFor(() => expect(document.activeElement).toBe(description));
    return description as HTMLTextAreaElement;
}

const category = () => screen.getByRole('button', { name: /^category/i });
const logRequest = () => screen.getByRole('button', { name: /log request/i });

beforeEach(() => {
    createManualIntake.mockClear();
    onCreated.mockClear();
    onClose.mockClear();
});
afterEach(cleanup);

describe('ManualIntake field labelling', () => {
    it('gives every field a real label, not a floating span', async () => {
        const user = userEvent.setup();
        await open();

        // getByLabelText only finds these if the association is programmatic.
        expect(screen.getByLabelText(/what is the caller reporting/i).tagName).toBe('TEXTAREA');
        expect(screen.getByLabelText(/callback number/i).tagName).toBe('INPUT');
        expect(screen.getByLabelText(/^location/i).tagName).toBe('INPUT');
        expect(category()).toBeTruthy();

        await user.click(screen.getByRole('button', { name: /caller details/i }));
        expect(screen.getByLabelText(/first name/i).tagName).toBe('INPUT');
        expect(screen.getByLabelText(/last name/i).tagName).toBe('INPUT');
        expect(screen.getByLabelText(/caller email/i).tagName).toBe('INPUT');
    });

    it('marks the required fields as required', async () => {
        await open();
        expect(category().getAttribute('aria-required')).toBe('true');
        expect(screen.getByLabelText(/what is the caller reporting/i)
            .getAttribute('aria-required')).toBe('true');
    });

    it('clicking a label moves focus to its field', async () => {
        const user = userEvent.setup();
        await open();

        await user.click(screen.getByText(/callback number/i));
        expect(document.activeElement).toBe(screen.getByLabelText(/callback number/i));
    });
});

describe('ManualIntake validation feedback', () => {
    it('keeps the submit buttons pressable so the form can answer', async () => {
        await open();
        expect((logRequest() as HTMLButtonElement).disabled).toBe(false);
    });

    it('announces the missing category and puts focus on it', async () => {
        const user = userEvent.setup();
        await open();

        await user.click(logRequest());

        /* Found by id, not by text or role: the app's shared assertive region
         * is a role="alert" holding the same words a moment later, so either
         * of those queries matches two nodes as soon as the timing shifts. */
        const alert = await waitFor(() => {
            const el = document.getElementById('intake-error')!;
            expect(el).toBeTruthy();
            return el;
        });
        expect(alert.getAttribute('role')).toBe('alert');
        expect(alert.textContent).toContain('Pick a category');
        // Focus is on the control at fault, not left on the button.
        expect(document.activeElement).toBe(category());
        expect(category().getAttribute('aria-invalid')).toBe('true');
        expect(category().getAttribute('aria-describedby')).toBe(alert.id);

        // And it reaches the app's live region, so it is spoken even though
        // focus moved somewhere that does not contain the message.
        await waitFor(() => {
            expect(document.getElementById('aria-live-region-assertive')!.textContent)
                .toContain('Pick a category');
        });
        expect(createManualIntake).not.toHaveBeenCalled();
    });

    it('moves focus to the description when only that is missing', async () => {
        const user = userEvent.setup();
        await open();

        category().focus();
        await user.keyboard('{ArrowDown}{Enter}');   // picks the first category
        await user.click(logRequest());

        const description = screen.getByLabelText(/what is the caller reporting/i);
        expect(document.activeElement).toBe(description);
        expect(description.getAttribute('aria-invalid')).toBe('true');
        await waitFor(() => {
            expect(document.getElementById('intake-error')!.textContent)
                .toContain('Add a short description');
        });
    });

    it('moves focus to a malformed email, inside the collapsed contact block', async () => {
        const user = userEvent.setup();
        const description = await open();

        category().focus();
        await user.keyboard('{ArrowDown}{Enter}');
        description.focus();
        await user.keyboard('Pothole outside the library');
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        const email = screen.getByLabelText(/caller email/i);
        email.focus();
        await user.keyboard('not-an-email');

        await user.click(logRequest());

        expect(document.activeElement).toBe(email);
        expect(email.getAttribute('aria-invalid')).toBe('true');
        expect(createManualIntake).not.toHaveBeenCalled();
    });

    it('announces the logged request id on success', async () => {
        const user = userEvent.setup();
        const description = await open();

        category().focus();
        await user.keyboard('{ArrowDown}{Enter}');
        description.focus();
        await user.keyboard('Pothole outside the library');
        await user.click(logRequest());

        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        await waitFor(() => {
            expect(document.getElementById('aria-live-region')!.textContent)
                .toContain('REQ-4242');
        });
    });
});

describe('ManualIntake category combobox', () => {
    const options = () => screen.getAllByRole('option');

    it('opens from the keyboard and moves a cursor with the arrow keys', async () => {
        const user = userEvent.setup();
        await open();

        category().focus();
        await user.keyboard('{ArrowDown}');

        const filter = await screen.findByRole('combobox', { name: /filter categories/i });
        // DOM focus belongs in the filter; the cursor is aria-activedescendant.
        expect(document.activeElement).toBe(filter);
        expect(category().getAttribute('aria-expanded')).toBe('true');
        expect(category().getAttribute('aria-controls'))
            .toBe(screen.getByRole('listbox').id);

        expect(options()).toHaveLength(3);
        expect(filter.getAttribute('aria-activedescendant')).toBe(options()[0].id);

        await user.keyboard('{ArrowDown}');
        expect(filter.getAttribute('aria-activedescendant')).toBe(options()[1].id);

        await user.keyboard('{ArrowUp}{ArrowUp}');   // wraps past the top
        expect(filter.getAttribute('aria-activedescendant')).toBe(options()[2].id);
    });

    it('selects with Enter and returns focus to the trigger', async () => {
        const user = userEvent.setup();
        await open();

        category().focus();
        await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');

        // The panel animates out, so its removal is awaited rather than assumed.
        await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
        expect(document.activeElement).toBe(category());
        expect(category().textContent).toContain('Streetlight Out');
    });

    it('filters as you type and selects the match with Enter', async () => {
        const user = userEvent.setup();
        await open();

        await user.click(category());
        const filter = await screen.findByRole('combobox', { name: /filter categories/i });
        await user.keyboard('graf');
        expect(options()).toHaveLength(1);

        await user.keyboard('{ArrowDown}{Enter}');
        await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
        expect(filter.isConnected).toBe(false);
        expect(category().textContent).toContain('Graffiti');
    });

    it('dismisses with Escape without closing the dialog, and restores focus', async () => {
        const user = userEvent.setup();
        await open();

        category().focus();
        await user.keyboard('{ArrowDown}');
        await screen.findByRole('listbox');

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
        expect(document.activeElement).toBe(category());
        expect(category().getAttribute('aria-expanded')).toBe('false');
        // Escape on the list must not take the whole intake dialog with it.
        expect(onClose).not.toHaveBeenCalled();
        expect(screen.getByRole('dialog')).toBeTruthy();
    });

    it('exposes the options as options, not as buttons inside a listbox', async () => {
        const user = userEvent.setup();
        await open();

        await user.click(category());
        const listbox = await screen.findByRole('listbox');
        // An invalid listbox is one whose children are anything else.
        expect(listbox.querySelectorAll('button')).toHaveLength(0);
        expect(options().every(o => o.getAttribute('role') === 'option')).toBe(true);
    });
});
