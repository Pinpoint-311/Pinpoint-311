import { describe, it, expect, vi, afterEach } from 'vitest';
import { chunkForTranslation, filterSupported, fetchSupportedLanguageCodes, resetSupportedLanguageCache, LANGUAGES } from './languages';

describe('chunkForTranslation', () => {
    it('splits by count', () => {
        const chunks = chunkForTranslation(Array.from({ length: 250 }, (_, i) => `t${i}`));
        expect(chunks.map(c => c.length)).toEqual([100, 100, 50]);
    });

    it('splits by characters so an anonymous request stays under the cap', () => {
        const paragraphs = Array.from({ length: 10 }, () => 'x'.repeat(1500));
        const chunks = chunkForTranslation(paragraphs);
        for (const c of chunks) expect(c.reduce((n, t) => n + t.length, 0)).toBeLessThanOrEqual(7500);
        expect(chunks.flat()).toHaveLength(10);
    });

    it('leaves out a string the endpoint would refuse', () => {
        expect(chunkForTranslation(['ok', 'y'.repeat(2001)])).toEqual([['ok']]);
    });
});

describe('supported languages', () => {
    afterEach(() => { resetSupportedLanguageCache(); vi.unstubAllGlobals(); });

    it('offers the full list until the server answers', () => {
        expect(filterSupported(null)).toBe(LANGUAGES);
    });

    it("narrows to the provider's codes, keeping English and the current choice", () => {
        const offered = filterSupported(['es', 'zh'], 'la').map(l => l.code).sort();
        expect(offered).toEqual(['en', 'es', 'la', 'zh']);
    });

    it('reads the codes from the public endpoint once', async () => {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ provider: 'aws', codes: ['es'] }) });
        vi.stubGlobal('fetch', fetchMock);
        expect(await fetchSupportedLanguageCodes()).toEqual(['es']);
        expect(await fetchSupportedLanguageCodes()).toEqual(['es']);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock).toHaveBeenCalledWith('/api/system/translate/languages');
    });

    it('falls back to null when the endpoint fails', async () => {
        vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
        expect(await fetchSupportedLanguageCodes()).toBeNull();
    });
});
