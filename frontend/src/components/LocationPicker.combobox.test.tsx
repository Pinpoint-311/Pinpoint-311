// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * Arrowing through address suggestions used to be silent.
 *
 * The list declared role="listbox" and the input declared role="combobox", but
 * the two were never connected: there was no aria-activedescendant, so the
 * highlight the arrow keys moved was a background colour and nothing more. A
 * screen-reader user could press Enter on a suggestion they had never been
 * told about. Worse, each role="option" wrapped a <button> -- prohibited
 * content for an option, and separately tabbable, so Tab walked into a list
 * meant to be driven by the arrow keys.
 *
 * The test drives it with real key presses, because the failure was precisely
 * that keys did nothing observable.
 */

const suggestionCalls: string[] = [];

vi.mock('../maps', async () => {
    const actual = await vi.importActual<any>('../maps');
    return {
        ...actual,
        // No credential: the picker falls back to the backend geocoder and
        // renders its own suggestion list, which is the list under test.
        hasMapCredential: () => false,
        createMap: vi.fn(async () => { throw new Error('no map'); }),
        createGeocoder: vi.fn(async () => null),
    };
});

vi.mock('../services/api', () => {
    const api: any = {
        geocodeAddress: vi.fn(async (query: string) => {
            suggestionCalls.push(query);
            return { formatted_address: `${query}, Testville, NJ`, lat: 40.2, lng: -74.0 };
        }),
        reverseGeocode: vi.fn(async () => null),
    };
    return { api, default: api };
});

import LocationPicker from './LocationPicker';

beforeEach(() => {
    suggestionCalls.length = 0;
});
afterEach(cleanup);

const openSuggestions = async (user: ReturnType<typeof userEvent.setup>) => {
    render(<LocationPicker config={{} as any} onChange={() => { }} />);
    const input = await screen.findByRole('combobox', { name: /Location or address/ });
    await user.click(input);
    await user.keyboard('12 Main Street');
    await screen.findByRole('listbox');
    return input;
};

describe('the address suggestion list', () => {
    it('is reachable and usable while the map SDK is still loading', async () => {
        render(<LocationPicker config={{} as any} onChange={() => { }} />);
        const input = await screen.findByRole('combobox', { name: /Location or address/ });
        // It used to be `disabled` until the SDK came up, which removed it from
        // the tab order underneath anyone already typing in it.
        expect((input as HTMLInputElement).disabled).toBe(false);
    });

    it('names the highlighted option on the combobox as the arrows move', async () => {
        const user = userEvent.setup();
        const input = await openSuggestions(user);

        expect(input.getAttribute('aria-expanded')).toBe('true');
        // Nothing highlighted yet, so nothing claimed to be active.
        expect(input.getAttribute('aria-activedescendant')).toBeNull();

        await user.keyboard('{ArrowDown}');

        await waitFor(() => expect(input.getAttribute('aria-activedescendant')).toBeTruthy());
        const activeId = input.getAttribute('aria-activedescendant')!;
        const option = document.getElementById(activeId)!;
        expect(option.getAttribute('role')).toBe('option');
        expect(option.getAttribute('aria-selected')).toBe('true');
        expect(option.textContent).toContain('12 Main Street');

        // DOM focus stays in the text box: that is what makes the combobox
        // pattern work, and what lets typing continue to narrow the list.
        expect(document.activeElement).toBe(input);
    });

    it('puts nothing tabbable inside the options', async () => {
        const user = userEvent.setup();
        await openSuggestions(user);

        const listbox = screen.getByRole('listbox');
        // role="option" prohibits interactive descendants; the <button> that
        // used to be here was also a second tab stop per suggestion.
        expect(listbox.querySelectorAll('button')).toHaveLength(0);
        expect(listbox.querySelectorAll('[tabindex]:not([tabindex="-1"])')).toHaveLength(0);
        expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    });

    it('drops the active-descendant claim when Escape closes the list', async () => {
        const user = userEvent.setup();
        const input = await openSuggestions(user);

        await user.keyboard('{ArrowDown}');
        await waitFor(() => expect(input.getAttribute('aria-activedescendant')).toBeTruthy());

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
        expect(input.getAttribute('aria-activedescendant')).toBeNull();
        expect(input.getAttribute('aria-expanded')).toBe('false');
    });
});
