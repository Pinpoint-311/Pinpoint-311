// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';

/**
 * WCAG 3.1.2 Language of Parts.
 *
 * `<html lang>` follows the reader's chosen language, so on a Spanish page
 * every string is announced with a Spanish voice — including the ones that
 * were never translated, because the request failed or is still in flight.
 * English words read by a Spanish synthesiser are not merely accented, they
 * are unintelligible. What is rendered has to say which language it is in.
 */

const state = { translated: 'Bache profundo', translating: false };

vi.mock('../hooks/useContentTranslation', () => ({
    useContentTranslation: () => ({
        translatedText: state.translated,
        isTranslating: state.translating,
    }),
}));

vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language: 'es', setLanguage: () => {}, isRTL: false }),
}));

import { TranslatedContent } from './TranslatedContent';

afterEach(cleanup);

describe('TranslatedContent language tagging', () => {
    it('tags translated text with the reader language', () => {
        state.translated = 'Bache profundo';
        state.translating = false;

        const { container } = render(
            <TranslatedContent text="Deep pothole" contentId="desc_1" />
        );

        expect(container.querySelector('span')!.getAttribute('lang')).toBe('es');
    });

    it('tags the original with the source language when translation did not happen', () => {
        // The hook falls back to the original string when the request fails,
        // so the page is Spanish and this text is not.
        state.translated = 'Deep pothole';
        state.translating = false;

        const { container } = render(
            <TranslatedContent text="Deep pothole" contentId="desc_2" />
        );

        expect(container.querySelector('span')!.getAttribute('lang')).toBe('en');
    });

    it('tags the placeholder shown while a translation is in flight', () => {
        state.translated = 'Deep pothole';
        state.translating = true;

        const { container } = render(
            <TranslatedContent text="Deep pothole" contentId="desc_3" />
        );

        expect(container.querySelector('span')!.getAttribute('lang')).toBe('en');
    });

    it('honours a caller-supplied source language', () => {
        state.translated = 'Bache profundo';
        state.translating = false;

        const { container } = render(
            <TranslatedContent text="Bache profundo" contentId="desc_4" sourceLang="es" />
        );

        expect(container.querySelector('span')!.getAttribute('lang')).toBe('es');
    });
});
