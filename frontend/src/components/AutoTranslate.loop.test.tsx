// @vitest-environment jsdom
import { describe, it, expect } from 'vitest';
// `?raw` rather than fs: this file is compiled by the production build as well
// as by vitest, and the build targets a browser where `fs`, `path` and
// `__dirname` do not exist. Vite inlines the file contents at both.
import SOURCE from './AutoTranslate.tsx?raw';

/**
 * The loop that billed.
 *
 * AutoTranslate applies translations as `node.textContent = translation`, and
 * its own MutationObserver watches characterData on the same subtree. So the
 * component's writes wake the observer that schedules the component. The
 * isTranslatingRef guard stops passes overlapping; it does not stop records
 * queued DURING a pass from being delivered after it clears, and the next pass
 * then reads the text this one just wrote.
 *
 * The source language is declared as English rather than detected, so
 * already-translated Spanish goes back as English source -- a new string every
 * time, which the cache cannot absorb. A demo holding 54 reports and 2,679
 * characters of description translated 674,448 characters in one day, and the
 * cache rows it left are Spanish text recorded with source_lang 'en'.
 *
 * Asserted against the source because the failure is structural and the
 * alternative -- driving jsdom through a real observer cycle with mocked fetch
 * -- pins the timing of an implementation rather than the property.
 */
describe('AutoTranslate does not feed its own writes back to the translator', () => {
    it('drains the mutations its own translation pass caused', () => {
        expect(SOURCE).toContain('takeRecords()');
    });

    it('drains before the concurrency guard drops, not after', () => {
        const drain = SOURCE.indexOf('observerRef.current?.takeRecords()');
        const release = SOURCE.indexOf('isTranslatingRef.current = false');
        expect(drain).toBeGreaterThan(-1);
        expect(release).toBeGreaterThan(-1);
        // Records discarded after the guard drops have already scheduled the
        // next pass, which is the whole failure.
        expect(drain).toBeLessThan(release);
    });

    it('drains on the restore-to-English path too', () => {
        // Restoring originals writes textContent as well, and those mutations
        // schedule a pass that has nothing to do.
        const occurrences = SOURCE.split('observerRef.current?.takeRecords()').length - 1;
        expect(occurrences).toBeGreaterThanOrEqual(2);
    });
});
