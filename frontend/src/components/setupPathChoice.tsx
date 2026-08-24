import { useEffect, useId, useRef, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';

import { ExternalLink } from 'lucide-react';

import { cloudForkFor, readPathChoice, subscribePathChoice, writePathChoice } from './setupSteps';
import type { CloudFork, PathLaunch, SetupPathId, StepContext } from './setupSteps';

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
            className="mb-5 rounded-2xl border border-white/12 bg-white/[0.03] p-5"
        >
            <h4 id={`${uid}-fork`} className="text-[15px] font-semibold text-white">
                Two ways to do this
            </h4>
            <p className="mt-1.5 text-[13px] text-white/60 leading-relaxed">{fork.question}</p>

            {/* Two cards of equal width, not a button beside a link.
             *
             * The old shape put a filled button and an underlined link on one
             * row, each with its blurb hanging underneath at a different
             * baseline, and the reader had to work out that these were two
             * answers to the same question. Equal panels say "choose one" by
             * their geometry. The emphasis that matters -- which most towns
             * should press -- is carried by the control inside the panel, and
             * by data-emphasis, rather than by making one option look like
             * body text. */}
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col rounded-xl border border-primary-400/30 bg-primary-500/[0.07] p-4">
                    <p className="text-[13px] text-white/70 leading-relaxed flex-1">
                        {fork.template.blurb}
                    </p>
                    <button
                        type="button"
                        data-setup-path="template"
                        data-emphasis="primary"
                        aria-describedby={`${uid}-fork`}
                        onClick={() => onPick('template')}
                        className="mt-3.5 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-primary-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-primary-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black/40 transition-colors"
                    >
                        {fork.template.label}
                    </button>
                </div>

                <div className="flex flex-col rounded-xl border border-white/12 bg-white/[0.02] p-4">
                    <p className="text-[13px] text-white/70 leading-relaxed flex-1">
                        {fork.manual.blurb}
                    </p>
                    <button
                        type="button"
                        data-setup-path="manual"
                        data-emphasis="secondary"
                        aria-describedby={`${uid}-fork`}
                        onClick={() => onPick('manual')}
                        className="mt-3.5 w-full inline-flex items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/[0.04] px-4 py-2.5 text-sm font-medium text-white/85 hover:bg-white/[0.09] hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black/40 transition-colors"
                    >
                        {fork.manual.label}
                    </button>
                </div>
            </div>

            {/* The reassurance, after the action rather than in front of it. */}
            <div className="mt-4 border-t border-white/8 pt-3.5">
                <p className="text-xs text-white/55 leading-relaxed">{fork.trust.line}</p>
                <details className="mt-1.5 group" data-testid="setup-path-trust">
                    <summary className="cursor-pointer text-xs text-primary-200 underline underline-offset-4 marker:text-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 rounded">
                        {fork.trust.summary}
                    </summary>
                    <div className="mt-2 text-xs text-white/60 leading-relaxed">{fork.trust.body}</div>
                </details>
            </div>
        </div>
    );
}

/**
 * The launch: the one link the template path exists to offer.
 *
 * Its own panel, above everything else on that path. It used to be the third
 * line of instruction 1, in the same type as the prose around it and below two
 * sentences of explanation -- so the single action the reader had just asked
 * for was something they had to find. Now the order matches what they are
 * doing: open the cloud's form, come back, paste what it printed.
 *
 * The link opens a new tab and says so. It leaves the site for the reader's own
 * cloud console, which is a thing to announce rather than spring: `rel` is set
 * because `target="_blank"` without it hands the opened page a handle back to
 * this one.
 */
export function SetupPathLaunch({ launch, uid }: { launch: PathLaunch; uid: string }) {
    return (
        <div
            data-testid="setup-path-launch"
            className="mb-4 rounded-xl border border-primary-400/30 bg-primary-500/[0.07] p-4"
        >
            <a
                href={launch.href}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="setup-path-launch-link"
                className="inline-flex items-center gap-2 rounded-lg bg-primary-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-primary-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black/40 transition-colors"
            >
                {launch.label}
                <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
                <span className="sr-only">(opens in a new tab)</span>
            </a>
            <p id={`${uid}-launch`} className="mt-2.5 text-[13px] text-white/65 leading-relaxed">
                {launch.line}
            </p>
            {launch.source && (
                <div className="mt-2 text-xs text-white/50 leading-relaxed">{launch.source}</div>
            )}
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
            {chosen === 'template' && fork.launch && <SetupPathLaunch launch={fork.launch} uid={uid} />}
            {chosen === 'template' ? template : manual}
            {chosen === 'template' && fork.templateExtras && (
                <details className="mt-4 group" data-testid="setup-path-extras">
                    <summary className="cursor-pointer text-xs text-primary-200 underline underline-offset-4 marker:text-white/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 rounded">
                        Optional hardening the template leaves to you
                    </summary>
                    <div className="mt-2 text-xs text-white/60 leading-relaxed">{fork.templateExtras}</div>
                </details>
            )}
        </>
    );
}
