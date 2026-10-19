/* Inline checks for the Branding page (WCAG 3.3.1 / 3.3.3).
 *
 * The custom domain used to be checked only by the server, after Configure
 * Domain, and Social Links took anything at all. These run as the admin types
 * or leaves a field, so the message sits next to the field it is about and
 * says how to fix it. Each returns an error message, or null when the value
 * is fine. */

const HOST_LABEL = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/i;

/** True for a bare host name like `311.yourtownship.gov`. */
function isHostName(host: string): boolean {
    if (host.length > 253) return false;
    const labels = host.split('.');
    if (labels.length < 2) return false;
    if (!labels.every((l) => HOST_LABEL.test(l))) return false;
    // The last label is the top-level domain: letters only, 2 or more.
    return /^[a-z]{2,63}$/i.test(labels[labels.length - 1]);
}

export const DOMAIN_EXAMPLE = '311.yourtownship.gov';

/**
 * Check a custom domain. An empty value is allowed (no custom domain) unless
 * `required` is set, as it is when the admin asks to configure one.
 */
export function validateDomain(raw: string | null | undefined, required = false): string | null {
    const value = (raw ?? '').trim();
    if (!value) return required ? `Enter a domain, like ${DOMAIN_EXAMPLE}.` : null;
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
        return `Enter the domain only, without http:// or https://. For example, ${DOMAIN_EXAMPLE}.`;
    }
    if (/\s/.test(value)) return 'A domain can\'t contain spaces.';
    if (value.includes('/')) return `Remove everything after the domain. For example, ${DOMAIN_EXAMPLE}.`;
    if (!value.includes('.')) return `Add the ending, like .gov or .org. For example, ${DOMAIN_EXAMPLE}.`;
    if (!isHostName(value)) {
        return `Enter a valid domain using letters, numbers, hyphens and dots. For example, ${DOMAIN_EXAMPLE}.`;
    }
    return null;
}

/** Hosts each platform's links are expected to live on. */
export const PLATFORM_HOSTS: Record<string, { label: string; hosts: string[] }> = {
    facebook: { label: 'Facebook', hosts: ['facebook.com', 'fb.com'] },
    instagram: { label: 'Instagram', hosts: ['instagram.com'] },
    twitter: { label: 'X (Twitter)', hosts: ['x.com', 'twitter.com'] },
    youtube: { label: 'YouTube', hosts: ['youtube.com', 'youtu.be'] },
    linkedin: { label: 'LinkedIn', hosts: ['linkedin.com'] },
};

function hostMatches(host: string, allowed: string): boolean {
    return host === allowed || host.endsWith(`.${allowed}`);
}

/** Check one social link URL against the platform chosen for it. */
export function validateSocialUrl(platform: string, raw: string | null | undefined): string | null {
    const value = (raw ?? '').trim();
    if (!value) return 'Enter a link, or remove this row.';
    if (!/^https?:\/\//i.test(value)) return 'Start the link with https://';
    let url: URL;
    try {
        url = new URL(value);
    } catch {
        return 'This isn\'t a valid web address. Check for typos.';
    }
    const host = url.hostname.toLowerCase();
    if (!isHostName(host)) return 'This isn\'t a valid web address. Check for typos.';
    const rule = PLATFORM_HOSTS[platform];
    if (rule && !rule.hosts.some((h) => hostMatches(host, h))) {
        return `This doesn't look like a ${rule.label} link. Use a ${rule.hosts.join(' or ')} address.`;
    }
    return null;
}
