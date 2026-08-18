// @vitest-environment jsdom
import type React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render as rtlRender, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The keyboard and screen-reader contract for the resident reporting flow.
 *
 * Three things were broken here, and each of them stops a keyboard-only or
 * screen-reader resident dead rather than merely inconveniencing them:
 *
 *  - The first-run disclaimer covers the entire portal and was a bare div.
 *    Nothing focused it, Tab walked straight out of it onto controls hidden
 *    behind the backdrop, and a screen reader announced the page underneath as
 *    if it were available.
 *  - Choosing a category replaces every node inside <main>. The button that
 *    caused it is unmounted with the rest, so focus fell to <body>: the next
 *    Tab restarted at the top of the document, and nothing said a new step had
 *    appeared.
 *  - Questions a municipality adds to a category rendered a floating <label>
 *    with no htmlFor and inputs with no id, so each one was announced as
 *    "edit, blank" and the placeholder was mistaken for the question.
 *
 * Real key presses throughout -- a synthetic click cannot tell you where focus
 * went, and where focus went is the entire subject.
 */

const { SERVICES } = vi.hoisted(() => ({ SERVICES: [
    {
        id: 1,
        service_code: 'pothole',
        service_name: 'Pothole',
        description: 'Damaged road surface',
        icon: 'Circle',
        routing_mode: 'internal',
        routing_config: {
            custom_questions: [
                { id: 'q1', label: 'Nearest cross street', type: 'text', required: true, placeholder: 'e.g. Oak Ave' },
                { id: 'q2', label: 'Is the road impassable?', type: 'yes_no', required: false },
                { id: 'q3', label: 'Which lane?', type: 'radio', required: false, options: ['Left', 'Right'] },
            ],
        },
    },
    {
        id: 2,
        service_code: 'streetlight',
        service_name: 'Streetlight Out',
        description: 'A light that will not come on',
        icon: 'Lightbulb',
        routing_mode: 'internal',
        routing_config: {},
    },
] }));

vi.mock('../services/api', () => {
    const api = {
        getServices: vi.fn().mockResolvedValue(SERVICES),
        getMapsConfig: vi.fn().mockResolvedValue({}),
        getMapLayers: vi.fn().mockResolvedValue([]),
        getPublicRequests: vi.fn().mockResolvedValue([]),
        roadCheck: vi.fn().mockResolvedValue({ blocked: false, detected_road: null }),
        createRequest: vi.fn().mockResolvedValue({ service_request_id: 'REQ-123' }),
    };
    return { api, default: api };
});

// The map canvas, the photo picker and the tracker are each covered elsewhere;
// what is under test is the portal's own keyboard behaviour.
vi.mock('../components/StaffDashboardMap', () => ({ default: () => null }));
vi.mock('../components/LocationPicker', () => ({ default: () => null }));
vi.mock('../components/TrackRequests', () => ({ default: () => null }));
vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville' }, isLoading: false, refreshSettings: () => { } }),
}));
vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language: 'en' }),
}));

import { MemoryRouter } from 'react-router-dom';
import { AccessibilityProvider } from '../context/AccessibilityContext';
import ResidentPortal from './ResidentPortal';

const render = (ui: React.ReactElement) =>
    rtlRender(ui, {
        wrapper: ({ children }) => (
            <MemoryRouter>
                <AccessibilityProvider>{children}</AccessibilityProvider>
            </MemoryRouter>
        ),
    });

// jsdom has no PointerEvent; framer-motion's keyboard press support fires one
// when Enter lands on a whileTap element.
if (typeof window.PointerEvent === 'undefined') {
    (window as any).PointerEvent = class PointerEvent extends MouseEvent { };
}

beforeEach(() => {
    localStorage.clear();
    // The portal reads its step from the URL hash, and jsdom keeps one window
    // for the whole file -- without this, a test that opened the report form
    // leaves the next one starting on it.
    window.history.replaceState(null, '', '/');
    window.scrollTo = vi.fn();
    if (!window.matchMedia) {
        (window as any).matchMedia = () => ({
            matches: false,
            addEventListener: () => { },
            removeEventListener: () => { },
        });
    }
    // jsdom has no rAF timing of its own worth waiting on; run it immediately so
    // the focus moves the components schedule land inside act().
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
        cb(0);
        return 0;
    });
    vi.stubGlobal('cancelAnimationFrame', () => { });
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as any;
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

/** Acknowledge the disclaimer the way a resident does, so the portal is usable. */
const dismissDisclaimer = async (user: ReturnType<typeof userEvent.setup>) => {
    const dialog = await screen.findByRole('dialog');
    await user.click(dialog.querySelector('input[type="checkbox"]')!);
    await user.click(await screen.findByRole('button', { name: /Let's Get Started/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
};

describe('the first-run non-emergency disclaimer', () => {
    it('is a dialog, named by its heading, and takes focus when it appears', async () => {
        render(<ResidentPortal />);

        const dialog = await screen.findByRole('dialog');
        expect(dialog.getAttribute('aria-modal')).toBe('true');
        // The name comes from the visible heading, not a duplicated aria-label.
        expect(dialog).toHaveProperty('id', '');
        expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)?.textContent)
            .toContain('Welcome to Testville');
        await waitFor(() => expect(document.activeElement).toBe(dialog));
    });

    it('keeps Tab inside itself instead of letting it reach the portal behind', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        const dialog = await screen.findByRole('dialog');

        const inDialog = () => dialog.contains(document.activeElement);

        // Well past the two controls the dialog holds: if the trap leaked, one
        // of these lands on the nav or the category grid behind the backdrop.
        for (let i = 0; i < 8; i++) {
            await user.tab();
            expect(inDialog()).toBe(true);
        }
        for (let i = 0; i < 8; i++) {
            await user.tab({ shift: true });
            expect(inDialog()).toBe(true);
        }
    });

    it('does not let Escape stand in for acknowledging the 911 notice', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        const dialog = await screen.findByRole('dialog');

        await user.keyboard('{Escape}');

        // Still there, still not acknowledged, and focus is on the way out --
        // the checkbox is the only thing that opens the portal.
        expect(screen.queryByRole('dialog')).toBe(dialog);
        expect(localStorage.getItem('disclaimer_acknowledged_v1')).toBeNull();
        expect(document.activeElement).toBe(dialog.querySelector('input[type="checkbox"]'));
    });

    it('lets the keyboard acknowledge it and then gets out of the way', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await screen.findByRole('dialog');

        await user.tab();
        expect((document.activeElement as HTMLInputElement).type).toBe('checkbox');
        await user.keyboard(' ');
        await user.tab();
        expect(document.activeElement).toHaveProperty('tagName', 'BUTTON');
        await user.keyboard('{Enter}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(localStorage.getItem('disclaimer_acknowledged_v1')).toBe('true');
    });
});

describe('moving between steps of a report', () => {
    it('puts focus on the new step heading rather than dropping it on the body', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await dismissDisclaimer(user);

        const category = await screen.findByRole('button', { name: /Pothole/ });
        await user.click(category);

        const heading = await screen.findByRole('heading', { level: 1, name: 'Pothole' });
        await waitFor(() => expect(document.activeElement).toBe(heading));
        expect(document.activeElement).not.toBe(document.body);
    });

    it('leaves exactly one level-one heading per view, inside <main>', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await dismissDisclaimer(user);

        await screen.findByRole('button', { name: /Pothole/ });
        let h1s = document.querySelectorAll('h1');
        expect(h1s).toHaveLength(1);
        expect(document.querySelector('main#main-content')!.contains(h1s[0])).toBe(true);

        await user.click(screen.getByRole('button', { name: /Pothole/ }));
        await screen.findByRole('heading', { level: 1, name: 'Pothole' });
        h1s = document.querySelectorAll('h1');
        expect(h1s).toHaveLength(1);
        expect(document.querySelector('main#main-content')!.contains(h1s[0])).toBe(true);
    });
});

describe('the questions a municipality adds to a category', () => {
    const openPotholeForm = async (user: ReturnType<typeof userEvent.setup>) => {
        render(<ResidentPortal />);
        await dismissDisclaimer(user);
        await user.click(await screen.findByRole('button', { name: /Pothole/ }));
        await screen.findByRole('heading', { level: 1, name: 'Pothole' });
    };

    it('names each field from its own label, not from its placeholder', async () => {
        const user = userEvent.setup();
        await openPotholeForm(user);

        // getByLabelText resolves through htmlFor/id, which is precisely what
        // was missing: before, this field had no accessible name at all.
        const crossStreet = screen.getByLabelText(/Nearest cross street/);
        expect(crossStreet.tagName).toBe('INPUT');

        await user.click(crossStreet);
        await user.keyboard('Oak Ave');
        expect((crossStreet as HTMLInputElement).value).toBe('Oak Ave');
    });

    it('groups choice questions so the question is announced with its options', async () => {
        const user = userEvent.setup();
        await openPotholeForm(user);

        // fieldset/legend, so the group carries the question as its name and
        // each option is a real radio that reports its own state.
        const impassable = screen.getByRole('group', { name: /Is the road impassable\?/ });
        const yes = screen.getByRole('radio', { name: 'Yes' });
        expect(impassable.contains(yes)).toBe(true);
        expect((yes as HTMLInputElement).checked).toBe(false);

        await user.click(yes);
        expect((yes as HTMLInputElement).checked).toBe(true);
        expect((screen.getByRole('radio', { name: 'No' }) as HTMLInputElement).checked).toBe(false);

        expect(screen.getByRole('group', { name: /Which lane\?/ })).toBeTruthy();
    });

    it('summarises what is wrong, moves focus to it, and links each message to its field', async () => {
        const user = userEvent.setup();
        await openPotholeForm(user);

        /* Everything the browser itself would refuse to submit is filled in
         * first: `required` fields are stopped by native constraint validation
         * before any handler runs, so the app's own rules -- a description that
         * is too short to act on -- are what this exercises. */
        await user.type(screen.getByLabelText(/Nearest cross street/), 'Oak Ave');
        await user.type(screen.getByLabelText(/^Email/), 'resident@example.gov');
        await user.type(screen.getByLabelText(/Description/), 'pothole');

        await user.click(screen.getByRole('button', { name: /Submit Request/ }));

        const summary = await screen.findByRole('alert', { name: /problem/i });
        await waitFor(() => expect(document.activeElement).toBe(summary));
        expect(summary.textContent).toContain('at least 10 characters');
        // The message links at the field it is about, by the field's own id.
        const link = summary.querySelector('a')!;
        expect(link.getAttribute('href')).toBe('#field-description');
        expect(document.getElementById('field-description')).toBeTruthy();

        // And the field itself says it is invalid and points back at the message.
        const description = screen.getByLabelText(/Description/);
        expect(description.getAttribute('aria-invalid')).toBe('true');
        const describedBy = description.getAttribute('aria-describedby')!;
        expect(document.getElementById(describedBy.split(' ')[0])!.textContent)
            .toContain('at least 10 characters');
    });

    it('declares the purpose of the personal-data fields so autofill can work', async () => {
        const user = userEvent.setup();
        await openPotholeForm(user);

        expect(screen.getByLabelText('First Name').getAttribute('autocomplete')).toBe('given-name');
        expect(screen.getByLabelText('Last Name').getAttribute('autocomplete')).toBe('family-name');
        expect(screen.getByLabelText(/^Email/).getAttribute('autocomplete')).toBe('email');
        expect(screen.getByLabelText(/Phone/).getAttribute('autocomplete')).toBe('tel');
    });
});
