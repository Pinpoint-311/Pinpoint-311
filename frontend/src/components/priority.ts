import { ServiceRequest } from '../types';

/**
 * What "high priority" means, once.
 *
 * The 1-10 scale was split into bands in eight places: the map's filter
 * predicate, the map's filter labels, the dashboard's distribution bar, the
 * dashboard's dropdown, the list filter, and three colour expressions on the
 * request detail. Each carried its own `>= 8` and its own "High (8-10)" text,
 * and the two kinds of duplicate fail differently.
 *
 * A threshold that drifts makes the counts disagree between two panels on the
 * same screen. A *label* that drifts is worse, because nothing disagrees: move
 * the boundary to 7 and the bar keeps saying "Medium (5-7)" over a bucket that
 * now starts at 5 and ends at 6, and it looks entirely correct.
 *
 * So the bands and the words for them come from the same array, and the labels
 * are computed from the bounds rather than typed alongside them.
 */

export type PriorityLevel = 'high' | 'medium' | 'low';

/**
 * Where a report sits when nothing has scored it.
 *
 * Middle of the scale, matching the backend, which uses 5 in the same
 * situation. Defaulting to low would quietly bury every report the AI has not
 * reached yet -- including, on a town with no AI configured, all of them.
 */
export const UNSCORED = 5;

interface Band {
    level: PriorityLevel;
    /** Inclusive lower bound. */
    min: number;
    /** Inclusive upper bound. */
    max: number;
    /** Tailwind text colour for the label. */
    text: string;
    /** Hex, for the map legend and anything drawing its own swatch. */
    hex: string;
}

/** Ordered high to low. The first band a score falls into wins. */
export const BANDS: readonly Band[] = [
    { level: 'high', min: 8, max: 10, text: 'text-red-300', hex: '#ef4444' },
    { level: 'medium', min: 5, max: 7, text: 'text-amber-300', hex: '#f59e0b' },
    { level: 'low', min: 1, max: 4, text: 'text-emerald-300', hex: '#22c55e' },
] as const;

/** "High (8-10)" — derived from the bounds, never typed next to them. */
export function bandLabel(level: PriorityLevel): string {
    const band = BANDS.find(b => b.level === level)!;
    const name = level.charAt(0).toUpperCase() + level.slice(1);
    return `${name} (${band.min}-${band.max})`;
}

export function bandFor(score: number): PriorityLevel {
    for (const band of BANDS) {
        if (score >= band.min) return band.level;
    }
    return 'low';
}

export function bandColor(level: PriorityLevel): string {
    return BANDS.find(b => b.level === level)!.hex;
}

/**
 * The score actually in force for a request.
 *
 * A staff member's manual score beats the AI's, which is the point of being
 * able to set one. `?? ` and not `||`, because a manual score of 0 is a
 * decision and `||` would discard it.
 */
export function scoreOf(request: Pick<ServiceRequest, 'manual_priority_score' | 'ai_analysis'> | Record<string, any>): number {
    const manual = (request as any).manual_priority_score;
    if (manual !== null && manual !== undefined) return manual;
    const ai = (request as any).ai_analysis;
    const scored = ai && typeof ai === 'object' ? ai.priority_score : undefined;
    return scored ?? UNSCORED;
}

export function levelOf(request: Parameters<typeof scoreOf>[0]): PriorityLevel {
    return bandFor(scoreOf(request));
}

/** How many requests fall in each band. One pass, so the parts sum to the whole. */
export function countByBand(requests: Array<Parameters<typeof scoreOf>[0]>): Record<PriorityLevel, number> {
    const counts: Record<PriorityLevel, number> = { high: 0, medium: 0, low: 0 };
    for (const request of requests) counts[levelOf(request)] += 1;
    return counts;
}
