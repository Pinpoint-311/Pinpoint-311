import { useEffect, useId, useRef, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';

import { cloudForkFor, readPathChoice, subscribePathChoice, writePathChoice } from './setupSteps';
import type { CloudFork, SetupPathId, StepContext } from './setupSteps';

/**
 * The one choice a cloud gets asked, and the way back out of it.
 *
 * Kept out of both callers because there are two: the guided walk asks it at
 * the top of the cloud task, straight after "which company hosts your town's
 * services", and a provider card asks it if the reader arrived there first.
 * One question, one stored answer, one set of words for it.
 *
 * Accessibility, decided once here rather than twice:
 *
 *   * Two buttons, not a radio group, and consistently so. A radio group is the
 *     right shape for a setting you adjust and then submit; this is two doors,
 *     each of which does something the moment it is pressed. Arrowing through
 *     radios that each swap the page underneath you is worse than two buttons
 *     that each say where they took you.
 *   * The emphasis is in the markup as well as the colour. `data-emphasis`
 *     names the primary action, so the distinction survives a stylesheet, a
 *     high-contrast mode, and a test.
 *   * No new live region. There is exactly one on this page, and a second
 *     polite region updating at the same moment is how a screen-reader user
 *     ends up hearing neither. Focus moves to the heading of what just
 *     appeared, which names the path and leaves the reader at the top of it.
 */

/** The stored choice for a cloud, and a setter that focuses what it reveals. */
export function usePathChoice(cloud: string) {
    const chosen = useSyncExternalStore(
        subscribePathChoice,
        () => readPathChoice(cloud),
        () => null,
    );

    const revealedRef = useRef<HTMLHeadingElement | null>(null);
    /* Only after a click. Focusing on mount because a previous visit is
     * remembered would yank focus out of whatever the clerk was doing. */
    const justPicked = useRef(false);
    useEffect(() => {
        if (justPicked.current && revealedRef.current) {
            justPicked.current = false;
            revealedRef.current.focus();
        }
    }, [chosen]);

    const pick = (choice: SetupPathId | null) => {
        justPicked.current = choice !== null;
        writePathChoice(cloud, choice);
    };

    return { chosen, pick, revealedRef };
}

/**
 * The fork: two ways to do the job, before anything is numbered.
 *
 * Two buttons rather than a radio group, deliberately and consistently. A radio
 * group is the right shape for a setting you adjust and then submit; this is
 * two doors, each of which does something the moment it is pressed, and a
 * screen-reader user arrowing through radios that each swap the page underneath
 * them is a worse experience than two buttons that each announce where they
 * took you. Both are keyboard-operable by definition, which the div-with-a-
 * click-handler this replaces was not.
 *
 * The emphasis is in the markup, not only in the colour: `data-emphasis` says
 * which is the primary action, so the distinction survives a stylesheet, a
 * high-contrast mode, and a test.
 */
export function SetupPathChoice({
    fork, uid, onPick,
}: {
    fork: CloudFork;
    uid: string;
    onPick: (choice: SetupPathId) => void;
}) {
    return (
        <div
            data-testid="setup-path-choice"
            className="mb-5 rounded-xl border border-white/15 bg-white/[0.04] p-4"
        >
            <h4 id={`${uid}-fork`} className="text-sm font-semibold text-white/85">
                Two ways to do this
            </h4>
            <p className="mt-1 text-xs text-white/60 leading-relaxed">{fork.question}</p>

            <div className="mt-3.5 flex flex-col gap-3 sm:flex-row sm:items-start">
                <div className="sm:max-w-xs">
                    <button
                        type="button"
                        data-setup-path="template"
                        data-emphasis="primary"
                        aria-describedby={`${uid}-template-blurb`}
                        onClick={() => onPick('template')}
                        className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-lg bg-primary-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-primary-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black/40 transition-colors"
                    >
                        {fork.template.label}
                    </button>
                    <p id={`${uid}-template-blurb`} className="mt-1.5 text-xs text-white/55 leading-relaxed">
                        {fork.template.blurb}
                    </p>
                </div>

                <div className="sm:pt-1.5 sm:max-w-xs">
                    <button
                        type="button"
                        data-setup-path="manual"
                        data-emphasis="secondary"
                        aria-describedby={`${uid}-manual-blurb`}
                        onClick={() => onPick('manual')}
                        className="inline-flex items-center rounded px-1 -mx-1 text-xs font-medium text-primary-200 underline underline-offset-4 hover:text-primary-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 transition-colors"
                    >
                        {fork.manual.label}
                    </button>
                    <p id={`${uid}-manual-blurb`} className="mt-1.5 text-xs text-white/55 leading-relaxed">
                        {fork.manual.blurb}
                    </p>
                </div>
            </div>

            {/* The reassurance, after the action rather than in front of it. */}
            <p className="mt-3.5 text-xs text-white/55 leading-relaxed">{fork.trust.line}</p>
            <details className="mt-1.5 group" data-testid="setup-path-trust">
                <summary className="cursor-pointer text-xs text-primary-200 underline underline-offset-4 marker:text-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 rounded">
                    {fork.trust.summary}
                </summary>
                <div className="mt-2 text-xs text-white/60 leading-relaxed">{fork.trust.body}</div>
            </details>
        </div>
    );
}

/**
 * The header above a chosen path, and the way back out of it.
 *
 * The heading takes focus when a path is picked, so the change of page is
 * announced by naming the walk the reader is now in. It is programmatically
 * focusable and not in the tab order -- a heading that traps a tab stop for
 * everybody in order to serve one moment is a regression for the clerk who is
 * simply tabbing to the first box.
 *
 * The switch is a button and always visible. Nothing entered is touched by
 * pressing it: the values live in the caller and the saved credentials live on
 * the server, and this changes only which description of the job is on screen.
 */
export function SetupPathBanner({
    fork, chosen, headingRef, uid, onPick,
}: {
    fork: CloudFork;
    chosen: SetupPathId;
    headingRef: React.MutableRefObject<HTMLHeadingElement | null>;
    uid: string;
    onPick: (choice: SetupPathId) => void;
}) {
    const other: SetupPathId = chosen === 'template' ? 'manual' : 'template';
    return (
        <div
            data-testid="setup-path-banner"
            data-setup-path-active={chosen}
            className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2"
        >
            <h4
                ref={headingRef}
                id={`${uid}-path`}
                tabIndex={-1}
                className="text-xs font-semibold text-white/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 rounded"
            >
                {fork[chosen].label}
            </h4>
            <button
                type="button"
                data-setup-path-switch={other}
                onClick={() => onPick(other)}
                className="inline-flex items-center rounded px-1 -mx-1 text-xs text-primary-200 underline underline-offset-4 hover:text-primary-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 transition-colors"
            >
                {fork[other].switchLabel}
            </button>
        </div>
    );
}


/**
 * A cloud's walk, behind its one choice.
 *
 * Renders the fork, then only the chosen side. A cloud with no template --
 * Google, deliberately and permanently -- has no fork registered, so this is
 * the manual walk and nothing else: no greyed-out button, no apology.
 */
export default function CloudSetupPath({
    cloud, ctx, template, manual,
}: {
    cloud: string;
    ctx: StepContext;
    template: ReactNode;
    manual: ReactNode;
}) {
    const fork = cloudForkFor(cloud, ctx);
    const { chosen, pick, revealedRef } = usePathChoice(cloud);
    const uid = useId();

    if (!fork) return <>{manual}</>;
    if (!chosen) return <SetupPathChoice fork={fork} uid={uid} onPick={pick} />;

    return (
        <>
            <SetupPathBanner fork={fork} chosen={chosen} headingRef={revealedRef} uid={uid} onPick={pick} />
            {chosen === 'template' ? template : manual}
        </>
    );
}
