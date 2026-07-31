import type { ReactNode } from 'react';

import type { Capability } from '../services/api';

/**
 * The setup instructions, as steps that own the boxes they produce.
 *
 * Instructions used to live in one long document at the top of the page while
 * the credential fields sat three thousand pixels below it, so following step
 * four meant scrolling away from the instruction to find the box and back up to
 * read the next one. The fix is not "put the instructions nearer the fields" --
 * it is that a step and the box it fills are one thing.
 *
 * The shape that makes that work is `fields`: the secret keys a step produces.
 * The card walks the steps in order, and after each one renders exactly the
 * inputs that step just told you how to obtain. `check` is the sentence that
 * says you are in the right place -- "you should see a page with boxes labelled
 * Domain, Client ID and Client Secret" -- which is only worth anything sitting
 * directly above those three boxes.
 *
 * Deliberately separate from ServiceProviders.tsx. The mechanism does not go
 * stale; vendor console paths do, and they will be filled in and corrected here
 * over time without touching a component.
 *
 * Two rules the card enforces, both of which exist so content can be incomplete
 * without breaking anything:
 *
 *   * a field no step claims still renders, at the end. Adding a credential to
 *     a catalog can never make it silently unreachable.
 *   * a provider with no steps at all falls back to the plain field list, which
 *     is what every provider had before this existed.
 */

export interface SetupStep {
    /** What to do. Rich, because it needs links, code spans and copy buttons. */
    body: ReactNode;
    /** How you know it worked, shown immediately above this step's fields. */
    check?: ReactNode;
    /** Secret keys this step produces, rendered as inputs directly beneath it. */
    fields?: string[];
    /** A caveat worth reading before the next step, not after it goes wrong. */
    /** A warning, in amber, with an icon.
     *
     * Reserved for a failure that is *silent* -- one where you would otherwise
     * think it had worked -- or *irreversible*, where there is no second
     * chance. Everything else belongs in `note`.
     *
     * The distinction is the whole point. There was a warning on every other
     * step and on all three steps of the Google Maps walk, and a page where
     * everything is flagged flags nothing: the billing warning, which is the
     * one that silently produces a grey map, sat in identical amber beside
     * "changes can take five minutes". */
    trouble?: ReactNode;
    /** A quiet aside. True, worth knowing, and not a warning: timing, a tip,
     *  an alternative. Grey, no icon, no urgency. */
    note?: ReactNode;
}

/** Everything a step-writer needs that depends on the deployment. */
export interface StepContext {
    /** This installation's origin, for callback URLs and key restrictions. */
    origin: string;
    /** Copy-to-clipboard, so a URL is never retyped by hand. */
    copy: (text: string, id: string) => void;
    /** Which id is currently showing its "copied" tick. */
    copied: string | null;
}

export type StepBuilder = (ctx: StepContext) => SetupStep[];

/**
 * Keyed `capability:provider`. Absent is a normal, supported state -- it means
 * the field labels already say everything, and the card shows them plainly.
 */
export const SETUP_STEPS: Partial<Record<string, StepBuilder>> = {};

/** Register a provider's steps. Kept as a function so the content file reads as
 *  a list of declarations rather than one enormous object literal. */
export function defineSteps(cap: Capability, provider: string, build: StepBuilder): void {
    SETUP_STEPS[`${cap}:${provider}`] = build;
}

export function stepsFor(cap: Capability, provider: string, ctx: StepContext): SetupStep[] {
    return SETUP_STEPS[`${cap}:${provider}`]?.(ctx) ?? [];
}

/** Field keys any step claims, so the card knows which are left over. */
export function claimedFields(steps: SetupStep[]): Set<string> {
    const claimed = new Set<string>();
    for (const step of steps) for (const key of step.fields ?? []) claimed.add(key);
    return claimed;
}
