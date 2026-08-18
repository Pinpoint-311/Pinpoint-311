// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';

/**
 * WCAG 3.1.2 Language of Parts.
 *
 * AutoTranslate rewrites text nodes in place — `node.textContent =
 * translation` — so once the pass has run there is nothing in the document
 * separating translated text from text it deliberately skipped. They are
 * siblings with identical markup. Meanwhile `<html lang>` has been switched to
 * the target language, which tells a screen reader to apply that language's
 * pronunciation to everything, including the English that was skipped: a
 * Spanish synthesiser reading an English code sample aloud, word by word.
 *
 * The only place the difference is still known is the skip branch itself, which
 * is where the `lang` stamp goes. Asserted here for both skip reasons — a
 * `code`/`pre` element and a `[data-no-translate]` subtree — plus the banner,
 * whose text is in the TARGET language despite carrying data-no-translate.
 */

let language = 'es';
vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language }),
}));

import { AutoTranslate } from './AutoTranslate';

beforeEach(() => {
    language = 'es';
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_url: string, init: any) => {
        const body = JSON.parse(init.body);
        return {
            ok: true,
            json: async () => ({ translations: body.texts.map((t: string) => `es:${t}`) }),
        };
    }));
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

function Page() {
    return (
        <AutoTranslate>
            <div>
                <p data-testid="prose">Report a pothole</p>
                <pre data-testid="sample">pip install requests</pre>
                <div data-no-translate data-testid="brand">
                    <span>Pinpoint 311</span>
                </div>
                <p lang="fr" data-no-translate data-testid="authored">Bonjour</p>
            </div>
        </AutoTranslate>
    );
}

describe('AutoTranslate language of parts', () => {
    it('stamps the authoring language on a code block it refused to translate', async () => {
        const { getByTestId } = render(<Page />);

        await waitFor(() => expect(getByTestId('sample').getAttribute('lang')).toBe('en'));
        // And its text really was left alone — otherwise the stamp would be a lie.
        expect(getByTestId('sample').textContent).toBe('pip install requests');
    });

    it('stamps it on a [data-no-translate] subtree too', async () => {
        const { getByTestId } = render(<Page />);

        await waitFor(() => expect(getByTestId('brand').getAttribute('lang')).toBe('en'));
        expect(getByTestId('brand').textContent).toBe('Pinpoint 311');
    });

    it('never overrides a lang the author set deliberately', async () => {
        const { getByTestId } = render(<Page />);

        await waitFor(() => expect(getByTestId('brand').getAttribute('lang')).toBe('en'));
        // The author said this is French. The heuristic does not get a vote.
        expect(getByTestId('authored').getAttribute('lang')).toBe('fr');
    });

    it('leaves translated prose alone — the document language already covers it', async () => {
        const { getByTestId } = render(<Page />);

        await waitFor(() => expect(getByTestId('prose').textContent).toBe('es:Report a pothole'));
        expect(getByTestId('prose').getAttribute('lang')).toBeNull();
    });

    it('tags the banner with the target language, because its text is in it', async () => {
        const { container } = render(<Page />);

        await waitFor(() => {
            const banner = container.querySelector('[data-no-translate].fixed');
            expect(banner).not.toBeNull();
            expect(banner!.getAttribute('lang')).toBe('es');
        });
    });

    it('renders no banner and stamps nothing when the page is already in the source language', async () => {
        language = 'en';
        const { container, getByTestId } = render(<Page />);

        await waitFor(() => expect(getByTestId('prose').textContent).toBe('Report a pothole'));
        expect(container.querySelector('[data-no-translate].fixed')).toBeNull();
    });
});
