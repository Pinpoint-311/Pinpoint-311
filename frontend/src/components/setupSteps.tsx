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

/**
 * The steps for a provider, for callers that only want to know there are some.
 *
 * A forked provider answers with its *manual* path rather than nothing. Two
 * reasons pointing the same way: the manual walk is the complete one, so it is
 * the honest answer to "what does setting this up involve"; and callers like
 * the provider card use a non-empty result to decide whether to render the walk
 * at all, so answering nothing would have hidden the fork along with the steps.
 * Drawing the fork itself is `forkFor`, below.
 */
export function stepsFor(cap: Capability, provider: string, ctx: StepContext): SetupStep[] {
    const own = SETUP_STEPS[`${cap}:${provider}`];
    if (own) return own(ctx);
    return SETUP_FORKS[`${cap}:${provider}`]?.(ctx).manual ?? [];
}

/** Field keys any step claims, so the card knows which are left over. */
export function claimedFields(steps: SetupStep[]): Set<string> {
    const claimed = new Set<string>();
    for (const step of steps) for (const key of step.fields ?? []) claimed.add(key);
    return claimed;
}

// ===========================================================================
// Two ways to do the same job
//
// Some clouds can be set up twice over: once by handing a template to the
// cloud's own deployment form, and once by walking the console. Both walks were
// written into the same numbered list, one after the other, which reads as one
// nine-step walk whose first step is optional -- and buries the two-minute path
// at the tail of a paragraph of trust copy. It also cannot be right for both
// readers: a town that will press the button does not want eight screens of
// portal navigation underneath it, and a government IT department that forbids
// templates outright -- many do -- should not have to read past a button they
// may not press to find the walk that is theirs.
//
// The choice is asked ONCE PER CLOUD, not once per capability. Azure's template
// creates the key vault, the OpenAI account and the multi-service AI account in
// one deployment: those belong to four different cards, so a fork living inside
// Key management would have hidden the control that sets up everything under
// one capability -- and hidden it completely from a town that unticked that
// capability. So the presentation of the choice belongs to the cloud
// (`defineCloudFork`) and only the two step lists belong to the capability
// (`defineFork`).
//
// The manual path is not a fallback and is never worded as one: it is the
// complete walk, numbered from 1, and it is the only path some towns are
// allowed to take.
// ===========================================================================

/** Which of the two paths a reader picked. Persisted per cloud. */
export type SetupPathId = 'template' | 'manual';

/** How one of the two paths is offered. Belongs to the cloud, not the card. */
export interface PathPresentation {
    /** The choice control's label. Says what you get, not what you click. */
    label: string;
    /** One line under the label: what this path actually involves. */
    blurb: ReactNode;
    /** The label on the control that switches *to* this path from the other
     *  one, read by someone already part-way through the other. */
    switchLabel: string;
}

/**
 * The launch itself: the one link that starts the deployment.
 *
 * On the fork rather than inside a numbered step, which is where it used to
 * live. A reader who has just pressed "Deploy with the template" is looking for
 * exactly one thing, and it was the third line of instruction 1, in the same
 * type as the prose around it. The single action a path exists to perform
 * should not have to be found.
 */
export interface PathLaunch {
    /** Where the cloud's own deployment form lives, template already loaded. */
    href: string;
    /** On the control. Names the destination, because it leaves the site. */
    label: string;
    /** One line under it: what pressing it opens, and what gets created. */
    line: ReactNode;
    /** Where the template can be read before it is run, for whoever asks. */
    source?: ReactNode;
}

export interface CloudFork {
    /** One sentence above the two choices. Neither path may be disparaged. */
    question: ReactNode;
    /** The primary action: fewer screens, and what most towns should press. */
    template: PathPresentation;
    /** Rendered above the template path once it is chosen. Absent means the
     *  path carries its own link, which is the shape this replaces. */
    launch?: PathLaunch;
    /** Hardening the template deliberately leaves to a person, folded shut at
     *  the foot of the template path. Not steps: a reader who chose the short
     *  path chose it to stop reading instructions, and numbering these rebuilds
     *  the manual walk inside it. Present for the town whose policy asks. */
    templateExtras?: ReactNode;
    /** The complete walk. Equal in standing, subordinate only in emphasis. */
    manual: PathPresentation;
    /**
     * The short line under the buttons, and the disclosure behind it.
     *
     * This is the reassurance a cautious IT department is actually reading, and
     * it used to sit *in front of* the button -- sixty words of it, with the
     * call to action at the end of them. Same words, moved behind the action:
     * see what to do, then check whether you may do it.
     */
    trust: { line: ReactNode; summary: string; body: ReactNode };
}

/** Keyed by cloud id (`azure`, `aws`). Google has no entry, deliberately: there
 *  is no true one-click equivalent, so there is no choice to offer and the
 *  manual walk is simply the walk. */
export const SETUP_CLOUD_FORKS: Partial<Record<string, (ctx: StepContext) => CloudFork>> = {};

export function defineCloudFork(cloud: string, build: (ctx: StepContext) => CloudFork): void {
    SETUP_CLOUD_FORKS[cloud] = build;
}

export function cloudForkFor(cloud: string, ctx: StepContext): CloudFork | null {
    return SETUP_CLOUD_FORKS[cloud]?.(ctx) ?? null;
}

/** One capability's two walks. The wording of the choice is the cloud's. */
export interface SetupFork {
    template: SetupStep[];
    manual: SetupStep[];
}

export type ForkBuilder = (ctx: StepContext) => SetupFork;

/** Keyed `capability:provider`, exactly like SETUP_STEPS. A provider appears in
 *  one registry or the other, never both. */
export const SETUP_FORKS: Partial<Record<string, ForkBuilder>> = {};

/** Register a capability's two walks on one cloud, in place of a single list. */
export function defineFork(cap: Capability, provider: string, build: ForkBuilder): void {
    SETUP_FORKS[`${cap}:${provider}`] = build;
}

export function forkFor(cap: Capability, provider: string, ctx: StepContext): SetupFork | null {
    return SETUP_FORKS[`${cap}:${provider}`]?.(ctx) ?? null;
}

/**
 * Every field either path claims.
 *
 * Before a reader has chosen, no steps are on screen, so nothing has claimed
 * anything -- and the card's "a field no step claims still renders, at the end"
 * rule would dump the whole credential form under the two buttons. The fields
 * are not unreachable, they are one click away, so the union of both paths is
 * the honest answer to what is claimed.
 */
export function forkFields(fork: SetupFork): Set<string> {
    return claimedFields([...fork.template, ...fork.manual]);
}

// ---------------------------------------------------------------------------
// Remembering the choice
//
// A UI preference, not configuration: it changes which of two correct
// descriptions of the same job is on screen and nothing about the deployment,
// so it does not belong in system settings, where one clerk's reading
// preference would be stored as if it were an operational fact and applied to
// everybody. Per browser is the right scope -- the clerk who picked is the
// clerk still reading.
//
// Keyed by cloud, so answering it in the guide answers it on the cards, and
// answering it on one card answers it on the next.
//
// Storage that throws (private mode, a locked-down profile) is not an error
// worth showing anybody: the choice still holds for this page, it just does not
// survive a reload, which is where the feature started.
// ---------------------------------------------------------------------------

const PATH_KEY = (cloud: string) => `pinpoint.setupPath.${cloud}`;

const pathListeners = new Set<() => void>();

/** The remembered choice for a cloud, or null for "has not chosen yet". */
export function readPathChoice(cloud: string): SetupPathId | null {
    try {
        const raw = window.localStorage.getItem(PATH_KEY(cloud));
        return raw === 'template' || raw === 'manual' ? raw : null;
    } catch {
        return null;
    }
}

/** Record a choice, or clear it with null. Notifies every mounted walk, because
 *  the same cloud can be on screen in the guide and on a card at once, and two
 *  copies disagreeing about which path you are on is worse than either. */
export function writePathChoice(cloud: string, choice: SetupPathId | null): void {
    try {
        if (choice) window.localStorage.setItem(PATH_KEY(cloud), choice);
        else window.localStorage.removeItem(PATH_KEY(cloud));
    } catch {
        /* Nothing to report: unremembered is the old behaviour, not a failure. */
    }
    for (const listener of [...pathListeners]) listener();
}

export function subscribePathChoice(listener: () => void): () => void {
    pathListeners.add(listener);
    return () => { pathListeners.delete(listener); };
}
