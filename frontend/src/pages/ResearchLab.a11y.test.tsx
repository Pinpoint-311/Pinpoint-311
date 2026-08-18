// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The research portal's keyboard and screen-reader contract.
 *
 * Three findings from the AA audit are pinned here because each of them is a
 * total loss of function for one group of users rather than a rough edge:
 *
 *   The Query Builder's three filters had labels sitting next to inputs with no
 *   id and no htmlFor. Visually a form; to a screen reader, three unnamed edit
 *   boxes. Nothing on the page said which was the start date.
 *
 *   The Python/R switcher looked like tabs and was two loose buttons, so it was
 *   two tab stops with no selected state exposed and no arrow-key behaviour —
 *   and the code it controlled was not connected to it in any way.
 *
 *   The app-wide skip link targets #main-content, and this route had no element
 *   with that id, so on the one page in the product with the longest header the
 *   link silently did nothing.
 *
 * All three are asserted through real keystrokes and document.activeElement,
 * because "the attribute is present" and "the keyboard works" are different
 * claims and only the second one is the requirement.
 */

const PYTHON_SNIPPET = 'import requests  # python snippet';


/* Defined inside the factory: vi.mock is hoisted above every top-level const,
 * so a mock that closes over one crashes on import. */
vi.mock('../services/api', () => {
    const api = {
        getResearchStatus: vi.fn().mockResolvedValue({ enabled: true }),
        getResearchAnalytics: vi.fn().mockResolvedValue({
            total_requests: 1234,
            avg_resolution_hours: 12.5,
            status_distribution: { open: 42 },
            category_distribution: [{ name: 'Pothole', count: 10 }],
        }),
        getResearchCodeSnippets: vi.fn().mockResolvedValue({
            python: 'import requests  # python snippet',
            r: 'library(httr)  # r snippet',
        }),
        getResearchDataDictionary: vi.fn().mockResolvedValue({
            research_packs: {},
            core_fields: [{ name: 'service_request_id', description: 'Identifier' }],
            fields: { service_request_id: {} },
        }),
        exportResearchCSV: vi.fn(),
        exportResearchGeoJSON: vi.fn(),
        exportDataDictionary: vi.fn(),
        researchChat: vi.fn().mockResolvedValue({ response: 'hello' }),
    };
    return { api, default: api };
});

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ user: { username: 'rmartin', role: 'researcher' } }),
}));

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville' } }),
}));

vi.mock('react-router-dom', () => ({
    useNavigate: () => vi.fn(),
}));


import { ResearchLab } from './ResearchLab';
import { AccessibilityProvider } from '../context/AccessibilityContext';
import SkipLink from '../components/SkipLink';

// jsdom implements neither of these, and AccessibilityProvider queries
// matchMedia on mount for the reduced-motion and high-contrast preferences.
if (typeof window.matchMedia !== 'function') {
    window.matchMedia = ((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener() { },
        removeListener() { },
        addEventListener() { },
        removeEventListener() { },
        dispatchEvent: () => false,
    })) as any;
}

// jsdom has no PointerEvent; framer-motion fires one on keyboard press.
if (typeof window.PointerEvent === 'undefined') {
    (window as any).PointerEvent = class PointerEvent extends MouseEvent { };
}

function renderLab(withSkipLink = false) {
    return render(
        <AccessibilityProvider>
            {withSkipLink && <SkipLink />}
            <ResearchLab />
        </AccessibilityProvider>
    );
}

beforeEach(() => {
    document.title = '';
});
afterEach(cleanup);

describe('ResearchLab Query Builder labels', () => {
    it('names each filter programmatically, not by proximity', async () => {
        renderLab();

        // getByLabelText resolves through htmlFor/id — proximity does not
        // satisfy it, which is the whole point of the assertion.
        const start = await screen.findByLabelText('Start Date');
        const end = screen.getByLabelText('End Date');
        const service = screen.getByLabelText('Service Category');

        expect(start.tagName).toBe('INPUT');
        expect(start.id).toBeTruthy();
        expect(end.id).toBeTruthy();
        expect(service.id).toBeTruthy();
        // Distinct ids, or one label points at the wrong box.
        expect(new Set([start.id, end.id, service.id]).size).toBe(3);
    });

    it('lets the keyboard reach and fill each filter by its name', async () => {
        const user = userEvent.setup();
        renderLab();

        const start = await screen.findByLabelText('Start Date');
        const service = screen.getByLabelText('Service Category');

        start.focus();
        expect(document.activeElement).toBe(start);

        await user.tab();
        expect(document.activeElement).toBe(screen.getByLabelText('End Date'));

        await user.tab();
        expect(document.activeElement).toBe(service);

        await user.keyboard('pothole');
        expect((service as HTMLInputElement).value).toBe('pothole');
    });
});

describe('ResearchLab snippet switcher', () => {
    it('is a tablist with one tab stop and a connected panel', async () => {
        renderLab();

        const tabs = await screen.findAllByRole('tab');
        expect(tabs.map(t => t.textContent)).toEqual(['Python', 'R']);
        expect((tabs[0] as HTMLButtonElement).tabIndex).toBe(0);
        expect((tabs[1] as HTMLButtonElement).tabIndex).toBe(-1);
        expect(tabs[0].getAttribute('aria-selected')).toBe('true');
        expect(tabs[1].getAttribute('aria-selected')).toBe('false');

        const panel = screen.getByRole('tabpanel');
        expect(panel.id).toBe(tabs[0].getAttribute('aria-controls'));
        expect(panel.getAttribute('aria-labelledby')).toBe(tabs[0].id);
        expect(panel.textContent).toContain('python snippet');
    });

    it('moves between tabs with the arrow keys and swaps the panel', async () => {
        const user = userEvent.setup();
        renderLab();

        const [python, r] = await screen.findAllByRole('tab');
        python.focus();
        expect(document.activeElement).toBe(python);

        await user.keyboard('{ArrowRight}');
        expect(document.activeElement).toBe(r);
        expect(r.getAttribute('aria-selected')).toBe('true');
        expect(python.getAttribute('aria-selected')).toBe('false');
        expect(screen.getByRole('tabpanel').textContent).toContain('r snippet');

        // Wraps rather than dead-ending, which is the pattern's contract.
        await user.keyboard('{ArrowRight}');
        expect(document.activeElement).toBe(python);

        await user.keyboard('{End}');
        expect(document.activeElement).toBe(r);
        await user.keyboard('{Home}');
        expect(document.activeElement).toBe(python);
    });

    it('leaves the tablist as a single Tab stop and lands on the panel next', async () => {
        const user = userEvent.setup();
        renderLab();

        const [python] = await screen.findAllByRole('tab');
        python.focus();

        await user.tab();

        // Not the second tab: the unselected one is out of the tab sequence.
        expect(document.activeElement).toBe(screen.getByRole('tabpanel'));
    });
});

describe('ResearchLab skip link target', () => {
    it('gives the app-wide skip link somewhere to go on this route', async () => {
        const user = userEvent.setup();
        renderLab(true);

        await screen.findByRole('tablist');

        const link = screen.getByRole('link', { name: 'Skip to main content' });
        link.focus();
        await user.keyboard('{Enter}');

        const main = document.getElementById('main-content');
        expect(main).not.toBeNull();
        expect(main!.tagName).toBe('MAIN');
        expect(document.activeElement).toBe(main);
    });
});

describe('ResearchLab privacy mode', () => {
    it('exposes which mode is selected rather than only colouring it', async () => {
        const user = userEvent.setup();
        renderLab();

        const fuzzed = await screen.findByRole('button', { name: /Fuzzed/ });
        const exact = screen.getByRole('button', { name: /^Exact$/ });

        expect(fuzzed.getAttribute('aria-pressed')).toBe('true');
        expect(exact.getAttribute('aria-pressed')).toBe('false');

        // A researcher is not an admin, so Exact is disabled — and the reason
        // must not be locked inside the disabled control.
        expect((exact as HTMLButtonElement).disabled).toBe(true);
        expect(screen.getByText(/administrators only/i)).toBeTruthy();

        await user.click(fuzzed);
        expect(fuzzed.getAttribute('aria-pressed')).toBe('true');
    });
});

describe('ResearchLab copy feedback', () => {
    it('says so when the clipboard write is refused', async () => {
        const user = userEvent.setup();
        Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
        });

        renderLab();

        const copy = await screen.findByRole('button', { name: 'Copy' });
        copy.focus();
        await user.keyboard('{Enter}');

        // The outcome is on the control itself, so it survives the live
        // region's three-second window and is there on the next visit.
        await waitFor(() => expect(screen.getByRole('button', { name: 'Copy failed' })).toBeTruthy());
    });

    it('confirms a successful copy', async () => {
        const user = userEvent.setup();
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

        renderLab();

        const copy = await screen.findByRole('button', { name: 'Copy' });
        await user.click(copy);

        expect(writeText).toHaveBeenCalledWith(PYTHON_SNIPPET);
        await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeTruthy());
    });
});

describe('ResearchLab status messages', () => {
    it('announces the query result instead of letting the numbers appear silently', async () => {
        const user = userEvent.setup();
        renderLab();

        const run = await screen.findByRole('button', { name: /Run Query/ });
        await user.click(run);

        // The app's single polite region, written through announce().
        const region = document.getElementById('aria-live-region')!;
        await waitFor(() => expect(region.textContent).toContain('1,234'));
    });
});
