/**
 * Where a deploy button sends Azure or AWS to fetch our template.
 *
 * A deploy button uploads nothing. It opens the provider's own deployment form
 * with a URL in it, and the *provider* fetches that URL -- Azure's portal reads
 * it cross-origin from portal.azure.com, CloudFormation reads it to render the
 * review page. So the address has to resolve from the public internet, not just
 * from the browser of the clerk pressing the button.
 *
 * The default answer used to be a constant pointing at
 * `raw.githubusercontent.com/.../main`. That works, and is wrong in three ways
 * that only show up later:
 *
 *   * a town on an older build got whatever is on `main` today, which can
 *     declare parameters that build's cards do not know how to consume;
 *   * a renamed repository, a private repository, or a government network that
 *     does not reach GitHub breaks every town's button at once;
 *   * a self-hoster who forked and edited the templates was still handed ours.
 *
 * So the first choice is the town's own instance, which serves the files at
 * `/api/deploy-templates/...` (see backend/app/api/deploy_templates.py). That
 * requires exactly one thing -- the instance being reachable from the internet
 * -- which is already true of a public 311 portal.
 *
 * When it plainly is not true, we fall back rather than break. An address that
 * only resolves inside the town network produces a fetch failure inside Azure's
 * portal, reported there as a broken template rather than as a wrong URL; a
 * slightly newer template from GitHub is the better failure. `describeSource`
 * exists so the page can say which of the two it used, because otherwise "why
 * did my deploy fail" has no answer visible from anywhere.
 */

/** Where the templates are published for anyone with no copy of their own. */
export const PUBLISHED_TEMPLATE_BASE_URL =
    'https://raw.githubusercontent.com/Pinpoint-311/Pinpoint-311/main/deploy/templates';

/** The path the instance serves them on. */
export const INSTANCE_TEMPLATE_PATH = '/api/deploy-templates';

export type TemplateSource = 'instance' | 'published';

export interface TemplateBase {
    /** Base URL to append `/azure/pinpoint-311.json` or `/aws/…yaml` to. */
    base: string;
    source: TemplateSource;
}

/**
 * Hostnames a cloud provider's servers cannot reach, whatever they resolve to
 * for the person looking at the page.
 *
 * Deliberately a denylist of the shapes that are *certainly* private rather
 * than an allowlist of public ones: a town on `311.somewhere.gov` must not be
 * demoted to the GitHub copy because a pattern failed to recognise it. The
 * cost of a false "public" is one hop to a URL that 404s; the cost of a false
 * "private" is silently serving a template from a repository the operator may
 * have forked away from. Neither is free, and this one is at least visible.
 */
function isUnreachableHost(host: string): boolean {
    const h = host.toLowerCase();
    if (h === 'localhost' || h === '::1' || h === '[::1]') return true;
    // Names with no dot at all resolve only inside somebody's own network.
    if (!h.includes('.')) return true;
    if (h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.lan') ||
        h.endsWith('.localhost') || h.endsWith('.home.arpa')) return true;

    const octets = h.split('.');
    if (octets.length === 4 && octets.every(o => /^\d{1,3}$/.test(o))) {
        const [a, b] = octets.map(Number);
        if (a === 127 || a === 10) return true;                 // loopback, RFC1918
        if (a === 192 && b === 168) return true;                // RFC1918
        if (a === 172 && b >= 16 && b <= 31) return true;       // RFC1918
        if (a === 169 && b === 254) return true;                // link-local
        if (a === 100 && b >= 64 && b <= 127) return true;      // CGNAT, RFC6598
        if (a === 0) return true;
    }
    return false;
}

/**
 * Whether a cloud provider's own servers could fetch a URL on this origin.
 *
 * Not "is this origin valid" and not "can my browser reach it" -- the browser
 * reaching it is exactly the assumption that produced redirect URIs no identity
 * provider could ever redirect to.
 */
export function isPubliclyReachable(origin: string | null | undefined): boolean {
    if (!origin) return false;
    let url: URL;
    try {
        url = new URL(origin);
    } catch {
        return false;
    }
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return false;
    return !isUnreachableHost(url.hostname);
}

/**
 * The base URL to build the two deploy links from.
 *
 * `origin` is the deployment's configured public origin where there is one and
 * the browser's origin otherwise -- the same `ctx.origin` every callback URL on
 * this page is built from, deliberately, so there is one answer to "what
 * address is this install on" rather than two that can disagree.
 */
export function templateBase(origin: string | null | undefined): TemplateBase {
    if (isPubliclyReachable(origin)) {
        return {
            base: `${String(origin).replace(/\/+$/, '')}${INSTANCE_TEMPLATE_PATH}`,
            source: 'instance',
        };
    }
    return { base: PUBLISHED_TEMPLATE_BASE_URL, source: 'published' };
}

/** Azure's documented portal entry point for a template at a URL. */
export function azureDeployUrl(base: string): string {
    // `intent` carries the cloud the reader picked in the guide, which lives in
    // this browser and nowhere the server can see. Without it the template
    // arrives with AI and translation switched off for someone the page has
    // just told that choosing a cloud moves them. It can only turn a toggle on.
    const url = `${base}/azure/pinpoint-311.json?intent=azure`;
    return `https://portal.azure.com/#create/Microsoft.Template/uri/${encodeURIComponent(url)}`;
}

/** CloudFormation's console entry point. Lands on the review screen, where a
 *  change set can be taken instead of a stack. */
export function awsDeployUrl(base: string): string {
    const url = `${base}/aws/pinpoint-311.yaml?intent=aws`;
    return `https://console.aws.amazon.com/cloudformation/home#/stacks/create/review?templateURL=${encodeURIComponent(url)}&stackName=pinpoint-311`;
}
