import { describe, it, expect } from 'vitest';

import { BANDS, UNSCORED, bandFor, bandLabel, countByBand, levelOf, scoreOf } from './priority';

/**
 * The 1-10 scale was banded in eight places, each with its own `>= 8` and its
 * own "High (8-10)" string.
 *
 * The two duplicates fail differently. A drifting *threshold* makes two panels
 * on the same screen disagree, which somebody eventually notices. A drifting
 * *label* is worse, because nothing disagrees: move the boundary to 7 and the
 * distribution bar goes on saying "Medium (5-7)" over a bucket that now runs 5
 * to 6, and it looks entirely correct.
 */

describe('the bands', () => {
    it('cover the whole scale with no gap and no overlap', () => {
        const seen = new Map<number, string>();
        for (let score = 1; score <= 10; score++) seen.set(score, bandFor(score));
        expect([...seen.values()]).toEqual([
            'low', 'low', 'low', 'low',        // 1-4
            'medium', 'medium', 'medium',      // 5-7
            'high', 'high', 'high',            // 8-10
        ]);
    });

    it('puts each boundary on the side its label claims', () => {
        expect(bandFor(4)).toBe('low');
        expect(bandFor(5)).toBe('medium');
        expect(bandFor(7)).toBe('medium');
        expect(bandFor(8)).toBe('high');
    });

    it('derives the label from the bounds rather than repeating them', () => {
        // The point of the whole module. These strings are computed from the
        // same numbers the predicate uses, so they cannot describe a band that
        // no longer exists.
        expect(bandLabel('high')).toBe('High (8-10)');
        expect(bandLabel('medium')).toBe('Medium (5-7)');
        expect(bandLabel('low')).toBe('Low (1-4)');
    });

    it('keeps every label consistent with its band, whatever the bounds are', () => {
        for (const band of BANDS) {
            expect(bandLabel(band.level)).toContain(`(${band.min}-${band.max})`);
            expect(bandFor(band.min)).toBe(band.level);
            expect(bandFor(band.max)).toBe(band.level);
        }
    });

    it('handles a score outside the scale rather than returning undefined', () => {
        expect(bandFor(0)).toBe('low');
        expect(bandFor(99)).toBe('high');
        expect(bandFor(-3)).toBe('low');
    });
});

describe('which score is in force', () => {
    it('prefers a staff member\'s manual score over the AI\'s', () => {
        expect(scoreOf({ manual_priority_score: 9, ai_analysis: { priority_score: 2 } })).toBe(9);
    });

    it('keeps a manual score of zero', () => {
        // `||` would discard it and fall through to the AI. A zero is somebody
        // deciding this is the lowest priority there is, not an absent value.
        expect(scoreOf({ manual_priority_score: 0, ai_analysis: { priority_score: 9 } })).toBe(0);
    });

    it('falls back to the AI score', () => {
        expect(scoreOf({ manual_priority_score: null, ai_analysis: { priority_score: 8 } })).toBe(8);
    });

    it('puts an unscored report in the middle, not at the bottom', () => {
        // Defaulting to low would bury every report the AI has not reached --
        // and on a town with no AI configured, that is all of them.
        expect(scoreOf({})).toBe(UNSCORED);
        expect(levelOf({})).toBe('medium');
        expect(scoreOf({ ai_analysis: null })).toBe(UNSCORED);
    });

    it('survives an ai_analysis that is not an object', () => {
        expect(scoreOf({ ai_analysis: 'pending' })).toBe(UNSCORED);
    });
});

describe('the distribution', () => {
    it('sums to the total, so the bar cannot show a gap', () => {
        const requests = [
            { manual_priority_score: 10 }, { manual_priority_score: 8 },
            { ai_analysis: { priority_score: 6 } }, {},
            { manual_priority_score: 1 }, { ai_analysis: { priority_score: 4 } },
        ];
        const counts = countByBand(requests);
        expect(counts).toEqual({ high: 2, medium: 2, low: 2 });
        expect(counts.high + counts.medium + counts.low).toBe(requests.length);
    });

    it('counts an empty list without dividing by anything', () => {
        expect(countByBand([])).toEqual({ high: 0, medium: 0, low: 0 });
    });
});
