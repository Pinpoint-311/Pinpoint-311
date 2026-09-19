// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * The four static pages -- privacy, terms, accessibility, 404.
 *
 * The markdown-ish renderer they share emitted <li> elements with no list
 * around them, so a screen reader had no list to announce: no "list, 9 items",
 * no position within it, and no way to skip past it. None of the four set a
 * document title either, so all four kept index.html's default -- the same
 * string in the tab, in the history, and in a bookmark, on four different
 * pages. And the app-wide skip link targets #main-content, which three of them
 * had and the 404 did not.
 */

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville' }, isLoading: false, refreshSettings: () => { } }),
}));

import PrivacyPolicy from './PrivacyPolicy';
import TermsOfService from './TermsOfService';
import AccessibilityPage from './AccessibilityPage';
import NotFoundPage from './NotFoundPage';

const PAGES = [
    { name: 'Privacy Policy', Page: PrivacyPolicy, title: /^Privacy Policy \| / },
    { name: 'Terms of Service', Page: TermsOfService, title: /^Terms of Service \| / },
    { name: 'Accessibility Statement', Page: AccessibilityPage, title: /^Accessibility Statement \| / },
    { name: 'Page not found', Page: NotFoundPage, title: /^Page not found/ },
];

beforeEach(() => { document.title = 'Municipality 311'; });
afterEach(cleanup);

describe.each(PAGES)('$name', ({ Page, title }) => {
    const show = () => render(<MemoryRouter><Page /></MemoryRouter>);

    it('sets a title of its own', () => {
        show();
        expect(document.title).toMatch(title);
    });

    it('restores the previous title when it goes away', () => {
        const { unmount } = show();
        unmount();
        expect(document.title).toBe('Municipality 311');
    });

    it('offers the landmark the app-wide skip link targets', () => {
        show();
        const main = document.querySelector('main#main-content');
        expect(main).not.toBeNull();
        // A landmark, not a div that happens to carry the id.
        expect(main!.tagName).toBe('MAIN');
    });
});

describe.each(PAGES.slice(0, 3))('$name list markup', ({ Page }) => {
    it('wraps its bullet points in a real list', () => {
        render(<MemoryRouter><Page /></MemoryRouter>);

        const lists = screen.getAllByRole('list');
        expect(lists.length).toBeGreaterThan(0);
        // Every list item belongs to one -- a bare <li> gets no list role at all
        // in the accessible tree, which is what the defect looked like.
        const items = Array.from(document.querySelectorAll('li'));
        expect(items.length).toBeGreaterThan(0);
        for (const item of items) {
            expect(item.parentElement!.tagName).toBe('UL');
        }
    });
});

describe('the accessibility statement', () => {
    it('no longer claims blanket keyboard access, and names the map as a limitation', () => {
        render(<MemoryRouter><AccessibilityPage /></MemoryRouter>);
        const text = document.body.textContent!;

        // The old wording was "All functionality is accessible via keyboard",
        // which was not true of the map and is the kind of claim an auditor
        // checks first.
        expect(text).not.toContain('All functionality is accessible via keyboard');
        expect(text).toContain('Known Limitations');
        expect(text).toMatch(/dragging it on the map is a pointer gesture/i);
    });
});
