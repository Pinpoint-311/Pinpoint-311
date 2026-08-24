/**
 * The setup questionnaire's answers, remembered between visits.
 *
 * They were not. `useState('google')` with no read and no write meant an admin
 * chose Microsoft Azure, followed the Azure walk, came back and was told they
 * had chosen Google — and the page then showed Google's instructions for
 * credentials they had already entered against Azure.
 *
 * WHAT THIS IS NOT. It is not where the deployment's providers live. Those are
 * server settings (`KMS_PROVIDER` and friends) written by a card's Save, and
 * they are what actually runs. This only remembers which set of instructions
 * the reader asked to see, which is why it is per browser and why it never
 * overrides the server: `preferStored` below takes the real setting whenever
 * there is one, so a town that switched key management to Azure on the card
 * opens the guide on Azure even in a browser that never answered the question.
 */

const PREFIX = 'pinpoint.setup.answer.';

/** A remembered answer, or `fallback` when there is none or it is unrecognised.
 *
 *  Validated against the options rather than trusted: the value survives a
 *  release, and a provider that has since been withdrawn would otherwise select
 *  itself forever from a string nothing offers any more. */
export function readSetupAnswer<T extends string>(
    question: string, allowed: readonly T[], fallback: T,
): T {
    try {
        const stored = window.localStorage.getItem(PREFIX + question);
        return (allowed as readonly string[]).includes(stored ?? '') ? (stored as T) : fallback;
    } catch {
        // Private mode, or storage disabled by policy. Remembering is a
        // convenience; refusing to render the page over it is not a trade
        // anybody would choose.
        return fallback;
    }
}

export function writeSetupAnswer(question: string, value: string): void {
    try {
        window.localStorage.setItem(PREFIX + question, value);
    } catch {
        /* see above */
    }
}

/**
 * The server's own answer when it has one, the remembered answer otherwise.
 *
 * The order matters and only one way round is defensible: what the deployment
 * actually runs outranks what somebody once ticked. A town whose key management
 * is set to Azure is an Azure town, whatever this browser last remembered.
 */
export function preferStored<T extends string>(
    stored: string | null | undefined, allowed: readonly T[], remembered: T,
): T {
    return (allowed as readonly string[]).includes(stored ?? '') ? (stored as T) : remembered;
}
