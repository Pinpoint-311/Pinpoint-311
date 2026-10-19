// @vitest-environment jsdom
import type React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render as rtlRender, screen, cleanup, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * Two resident-side navigation bugs.
 *
 *  - 002: "Back to Home" on the tracker, reached from the confirmation screen,
 *    changed the URL to the root but left the "Request submitted" screen up,
 *    because it hid the tracker without resetting the portal's step.
 *  - 001: following "Terms of Service" from the middle of a report and
 *    pressing the Terms page's back arrow landed on the home page with the
 *    report gone. The arrow pushed a fresh "/" instead of going back, and the
 *    form kept nothing once it unmounted.
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

const { createRequest } = vi.hoisted(() => ({
    createRequest: vi.fn().mockResolvedValue({ service_request_id: 'REQ-123' }),
}));

vi.mock('../services/api', () => {
    const api = {
        getServices: vi.fn().mockResolvedValue(SERVICES),
        getMapsConfig: vi.fn().mockResolvedValue({}),
        getMapLayers: vi.fn().mockResolvedValue([]),
        getPublicRequests: vi.fn().mockResolvedValue([]),
        roadCheck: vi.fn().mockResolvedValue({ blocked: false, detected_road: null }),
        createRequest,
    };
    return { api, default: api };
});

vi.mock('../components/StaffDashboardMap', () => ({ default: () => null }));
vi.mock('../components/LocationPicker', () => ({ default: () => null }));
vi.mock('../components/TrackRequests', () => ({
    default: () => <div data-testid="tracker">tracker</div>,
}));
vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville' }, isLoading: false, refreshSettings: () => { } }),
}));
vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language: 'en', setLanguage: () => { } }),
}));

import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AccessibilityProvider } from '../context/AccessibilityContext';
import ResidentPortal from './ResidentPortal';
import TermsOfService from './TermsOfService';
import PrivacyPolicy from './PrivacyPolicy';
import AccessibilityPage from './AccessibilityPage';
import { RESIDENT_DRAFT_KEY } from '../utils/residentDraft';

const render = (ui: React.ReactElement) =>
    rtlRender(ui, {
        wrapper: ({ children }) => (
            <MemoryRouter>
                <AccessibilityProvider>{children}</AccessibilityProvider>
            </MemoryRouter>
        ),
    });

if (typeof window.PointerEvent === 'undefined') {
    (window as any).PointerEvent = class PointerEvent extends MouseEvent { };
}

beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('disclaimer_acknowledged_v1', 'true');
    window.history.replaceState(null, '', '/');
    window.scrollTo = vi.fn();
    if (!window.matchMedia) {
        (window as any).matchMedia = () => ({
            matches: false,
            addEventListener: () => { },
            removeEventListener: () => { },
        });
    }
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
        cb(0);
        return 0;
    });
    vi.stubGlobal('cancelAnimationFrame', () => { });
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }) as any;
    createRequest.mockClear();
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

type User = ReturnType<typeof userEvent.setup>;

const openPothole = async (user: User) => {
    await user.click(await screen.findByRole('button', { name: /Pothole/ }));
    await screen.findByRole('heading', { level: 1, name: 'Pothole' });
};

const fillPothole = async (user: User) => {
    await user.type(screen.getByLabelText(/Description/), 'Deep pothole by the school');
    await user.type(screen.getByLabelText(/Nearest cross street/), 'Oak Ave');
    await user.type(screen.getByLabelText(/^Email/), 'resident@example.com');
};

const popTo = (hash: string) => {
    act(() => {
        window.history.pushState(null, '', hash ? `/#${hash}` : '/');
        window.dispatchEvent(new PopStateEvent('popstate'));
    });
};

describe('issue 002: Back to Home from the tracker', () => {
    it('shows the catalog, not the old confirmation, and focuses the home heading', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await openPothole(user);
        await fillPothole(user);
        await user.click(screen.getByRole('button', { name: /Submit Request/ }));
        await screen.findByRole('heading', { level: 1, name: 'Request submitted' });
        expect(window.location.hash).toBe('#success');

        await user.click(screen.getByRole('button', { name: /Track this request/ }));
        await screen.findByTestId('tracker');
        expect(window.location.hash).toBe('#track/REQ-123');

        await user.click(screen.getByRole('button', { name: /Go back to home page/ }));

        const home = await screen.findByRole('heading', { level: 1, name: 'How can we help?' });
        expect(screen.queryByText('Request submitted')).toBeNull();
        expect(screen.queryByTestId('tracker')).toBeNull();
        expect(window.location.hash).toBe('');
        await waitFor(() => expect(document.activeElement).toBe(home));
        expect(window.scrollTo).toHaveBeenCalled();

        // The submission and the form are gone: starting again is a blank form.
        await openPothole(user);
        expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value).toBe('');
        expect((screen.getByLabelText(/^Email/) as HTMLInputElement).value).toBe('');
    });

    it('a browser navigation to the root also leaves the confirmation behind', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await openPothole(user);
        await fillPothole(user);
        await user.click(screen.getByRole('button', { name: /Submit Request/ }));
        await screen.findByRole('heading', { level: 1, name: 'Request submitted' });

        popTo('');
        await screen.findByRole('heading', { level: 1, name: 'How can we help?' });
        expect(screen.queryByText('Request submitted')).toBeNull();
    });

    it('Back from the tracker returns to the confirmation; Back from it opens a fresh form', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await openPothole(user);
        await fillPothole(user);
        await user.click(screen.getByRole('button', { name: /Submit Request/ }));
        await screen.findByRole('heading', { level: 1, name: 'Request submitted' });
        await user.click(screen.getByRole('button', { name: /Track this request/ }));
        await screen.findByTestId('tracker');

        popTo('success');
        await screen.findByRole('heading', { level: 1, name: 'Request submitted' });

        // Not the filled-in form that was just filed -- no duplicate submit.
        popTo('report/pothole');
        await screen.findByRole('heading', { level: 1, name: 'Pothole' });
        await waitFor(() =>
            expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value).toBe(''),
        );
    });

    it('Forward onto a confirmation that was reset goes home instead of an empty success screen', async () => {
        render(<ResidentPortal />);
        await screen.findByRole('heading', { level: 1, name: 'How can we help?' });
        popTo('success');
        await screen.findByRole('heading', { level: 1, name: 'How can we help?' });
        expect(screen.queryByText('Request submitted')).toBeNull();
        expect(window.location.hash).toBe('');
    });
});

describe('issue 001: the in-progress report survives a visit to the Terms', () => {
    it('saves the draft to sessionStorage (not localStorage) and restores it on return', async () => {
        const user = userEvent.setup();
        const first = render(<ResidentPortal />);
        await openPothole(user);
        await fillPothole(user);

        const saved = JSON.parse(sessionStorage.getItem(RESIDENT_DRAFT_KEY)!);
        expect(saved.service_code).toBe('pothole');
        expect(saved.description).toBe('Deep pothole by the school');
        expect(saved.email).toBe('resident@example.com');
        expect(saved.custom_answers).toEqual({ 'Nearest cross street': 'Oak Ave' });
        expect(saved.preferred_language).toBe('en');
        expect(JSON.stringify(localStorage)).not.toContain('resident@example.com');

        // Leaving for /terms unmounts the portal; coming back remounts it on
        // the same #report/pothole entry.
        first.unmount();
        expect(window.location.hash).toBe('#report/pothole');
        render(<ResidentPortal />);

        await screen.findByRole('heading', { level: 1, name: 'Pothole' });
        await waitFor(() =>
            expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value)
                .toBe('Deep pothole by the school'),
        );
        expect((screen.getByLabelText(/^Email/) as HTMLInputElement).value).toBe('resident@example.com');
        expect((screen.getByLabelText(/Nearest cross street/) as HTMLInputElement).value).toBe('Oak Ave');
        expect(screen.queryByText('Add your photos again.')).toBeNull();
    });

    it('asks for photos again, since they are never stored', async () => {
        sessionStorage.setItem(RESIDENT_DRAFT_KEY, JSON.stringify({
            service_code: 'pothole', description: 'Deep pothole', address: '', lat: null, lng: null,
            first_name: '', last_name: '', email: '', phone: '', is_public: true,
            custom_answers: {}, preferred_language: 'en', photo_count: 2,
        }));
        window.history.replaceState(null, '', '/#report/pothole');
        render(<ResidentPortal />);
        await screen.findByRole('heading', { level: 1, name: 'Pothole' });
        expect(await screen.findByText('Add your photos again.')).toBeTruthy();
        expect(sessionStorage.getItem(RESIDENT_DRAFT_KEY)).not.toMatch(/data:image|base64/);
    });

    it('does not restore a draft into a different category', async () => {
        sessionStorage.setItem(RESIDENT_DRAFT_KEY, JSON.stringify({
            service_code: 'pothole', description: 'Deep pothole', address: '', lat: null, lng: null,
            first_name: '', last_name: '', email: 'a@b.co', phone: '', is_public: true,
            custom_answers: {}, preferred_language: 'en', photo_count: 0,
        }));
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await user.click(await screen.findByRole('button', { name: /Streetlight Out/ }));
        await screen.findByRole('heading', { level: 1, name: 'Streetlight Out' });
        expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value).toBe('');
    });

    it('clears the draft, contact details included, on a successful submit', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await openPothole(user);
        await fillPothole(user);
        expect(sessionStorage.getItem(RESIDENT_DRAFT_KEY)).not.toBeNull();
        await user.click(screen.getByRole('button', { name: /Submit Request/ }));
        await screen.findByRole('heading', { level: 1, name: 'Request submitted' });
        expect(sessionStorage.getItem(RESIDENT_DRAFT_KEY)).toBeNull();
    });

    it('clears the draft when the resident deliberately goes back to the categories', async () => {
        const user = userEvent.setup();
        render(<ResidentPortal />);
        await openPothole(user);
        await fillPothole(user);
        await user.click(screen.getByRole('button', { name: /Back to categories/ }));
        await screen.findByRole('heading', { level: 1, name: 'How can we help?' });
        expect(sessionStorage.getItem(RESIDENT_DRAFT_KEY)).toBeNull();
    });

    it('keeps working when sessionStorage throws', async () => {
        const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('QuotaExceededError');
        });
        try {
            const user = userEvent.setup();
            render(<ResidentPortal />);
            await openPothole(user);
            await user.type(screen.getByLabelText(/Description/), 'Still typing fine');
            expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value).toBe('Still typing fine');
        } finally {
            spy.mockRestore();
        }
    });

    it('end to end: Terms link, back arrow, form is still filled in', async () => {
        const user = userEvent.setup();
        rtlRender(
            <MemoryRouter initialEntries={['/']}>
                <AccessibilityProvider>
                    <Routes>
                        <Route path="/" element={<ResidentPortal />} />
                        <Route path="/terms" element={<TermsOfService />} />
                    </Routes>
                </AccessibilityProvider>
            </MemoryRouter>,
        );
        await openPothole(user);
        await fillPothole(user);

        const form = screen.getByRole('button', { name: /Submit Request/ }).closest('form')!;
        const termsLink = Array.from(form.querySelectorAll('a')).find((a) => a.textContent === 'Terms of Service')!;
        // Same tab, so the back arrow has somewhere to go back to.
        expect(termsLink.getAttribute('target')).toBeNull();
        await user.click(termsLink);
        await screen.findByRole('heading', { level: 1, name: /Terms of Service/ });

        await user.click(screen.getByRole('link', { name: 'Go back' }));
        await screen.findByRole('heading', { level: 1, name: 'Pothole' });
        await waitFor(() =>
            expect((screen.getByLabelText(/Description/) as HTMLTextAreaElement).value)
                .toBe('Deep pothole by the school'),
        );
        expect((screen.getByLabelText(/^Email/) as HTMLInputElement).value).toBe('resident@example.com');
    });
});

describe.each([
    { name: 'Terms of Service', Page: TermsOfService, path: '/terms' },
    { name: 'Privacy Policy', Page: PrivacyPolicy, path: '/privacy' },
    { name: 'Accessibility', Page: AccessibilityPage, path: '/accessibility' },
])('the $name back arrow', ({ Page, path }) => {
    const show = (entries: string[]) =>
        rtlRender(
            <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
                <Routes>
                    <Route path="/" element={<div>HOME</div>} />
                    <Route path="/somewhere" element={<div>WHERE I CAME FROM</div>} />
                    <Route path={path} element={<Page />} />
                </Routes>
            </MemoryRouter>,
        );

    it('goes back to where the resident came from', async () => {
        const user = userEvent.setup();
        // MemoryRouter keys only its first entry "default", so the page being
        // second is the same as having arrived by an in-app navigation.
        show(['/somewhere', path]);
        await user.click(screen.getByRole('link', { name: 'Go back' }));
        expect(await screen.findByText('WHERE I CAME FROM')).toBeTruthy();
    });

    it('falls back to home when there is no in-app history', async () => {
        const user = userEvent.setup();
        rtlRender(
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    <Route path="/" element={<div>HOME</div>} />
                    <Route path={path} element={<Page />} />
                </Routes>
            </MemoryRouter>,
        );
        await user.click(screen.getByRole('link', { name: 'Go back' }));
        expect(await screen.findByText('HOME')).toBeTruthy();
    });
});
