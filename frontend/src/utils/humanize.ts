/**
 * Turn a machine value (`login_success`, `push-status`, `pushStatus`,
 * `setup.complete`) into the words a person reads ("Login success",
 * "Push status", "Setup complete").
 *
 * Sentence case, not Title Case: only the first word is capitalised, plus any
 * word the dictionary below knows the proper spelling of (AI, SMS, ArcGIS...).
 *
 * Use it for enum-ish values only. Identifiers a person has to copy or match
 * exactly (request IDs, commit hashes, URLs, vendor field names) must be shown
 * as they are.
 */

/** Words whose casing isn't "first letter up, rest down". Keys are lowercase. */
const PROPER: Record<string, string> = {
    ai: 'AI',
    api: 'API',
    apis: 'APIs',
    arcgis: 'ArcGIS',
    auth0: 'Auth0',
    aws: 'AWS',
    azure: 'Azure',
    bedrock: 'Bedrock',
    claude: 'Claude',
    crm: 'CRM',
    csv: 'CSV',
    dns: 'DNS',
    esri: 'Esri',
    gcp: 'GCP',
    gemini: 'Gemini',
    gis: 'GIS',
    github: 'GitHub',
    google: 'Google',
    http: 'HTTP',
    https: 'HTTPS',
    id: 'ID',
    ids: 'IDs',
    ip: 'IP',
    json: 'JSON',
    kms: 'KMS',
    llm: 'LLM',
    mfa: 'MFA',
    oauth: 'OAuth',
    ocr: 'OCR',
    openai: 'OpenAI',
    open311: 'Open311',
    osm: 'OSM',
    pdf: 'PDF',
    pii: 'PII',
    sendgrid: 'SendGrid',
    sentry: 'Sentry',
    sms: 'SMS',
    smtp: 'SMTP',
    sso: 'SSO',
    ssl: 'SSL',
    tls: 'TLS',
    twilio: 'Twilio',
    url: 'URL',
    urls: 'URLs',
    vertex: 'Vertex',
};

/** Split snake_case, kebab-case, dotted.names, spaced words and camelCase. */
const words = (value: string): string[] =>
    value
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
        .split(/[\s_.\-/]+/)
        .filter(Boolean);

export function humanize(value: string | null | undefined): string {
    if (value === null || value === undefined) return '';
    let raw = String(value);
    // SCREAMING_SNAKE (env-style keys) carries no casing information.
    if (/[_\-.]/.test(raw) && raw === raw.toUpperCase()) raw = raw.toLowerCase();
    const parts = words(raw);
    return parts
        .map((w, i) => {
            const proper = PROPER[w.toLowerCase()];
            if (proper) return proper;
            // Keep an all-caps acronym the caller already wrote (e.g. "NJ").
            if (w.length > 1 && w === w.toUpperCase() && /[A-Z]/.test(w)) return w;
            const lower = w.toLowerCase();
            return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
        })
        .join(' ');
}

/** humanize(), but every word capitalised -- for proper names such as a vendor. */
export function humanizeTitle(value: string | null | undefined): string {
    return humanize(value)
        .split(' ')
        .map(w => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
        .join(' ');
}

/** True for a bare snake_case enum value (`not_configured`, `google_secret_manager`)
 *  as opposed to free text, a number, a path or an identifier with digits. */
export function isEnumLike(value: unknown): value is string {
    return typeof value === 'string' && /^[a-z]+(_[a-z]+)+$/.test(value);
}
