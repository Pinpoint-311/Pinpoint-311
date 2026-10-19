// Pure helpers for server.js, kept free of side effects (no listen, no cron)
// so they can be unit-tested with `node --test`.

export function sanitizeForLog(str) {
    if (typeof str !== 'string') return String(str);
    return str.replace(/[\r\n\t]/g, ' ').replace(/[\x00-\x1f\x7f]/g, '').slice(0, 200);
}

export function validateId(id) {
    return typeof id === 'string' && /^[a-z0-9]{4,8}$/.test(id);
}

export function validatePort(port) {
    return Number.isInteger(port) && port >= 1024 && port <= 65535;
}

// Town names are written into the production Caddyfile (as a comment) and
// echoed back by the API. A newline or brace there would let a visitor add
// their own Caddy site blocks, so keep only characters a town name needs.
export const TOWN_NAME_MAX = 80;
export function sanitizeTownName(name) {
    if (typeof name !== 'string') return '';
    return name
        .replace(/\s/g, ' ')
        .replace(/[^\p{L}\p{N} .,'&-]/gu, '')
        .replace(/ +/g, ' ')
        .trim()
        .slice(0, TOWN_NAME_MAX);
}

// docker compose invocation as an argv array plus env, for execFile: no shell
// ever parses these values, so nothing in them can become a second command.
export function composeInvocation(config, id, port, actionArgs) {
    if (!validateId(id)) throw new Error('Invalid instance ID');
    if (!validatePort(port)) throw new Error('Invalid port');
    const offset = port - config.BASE_PORT;
    return {
        file: 'docker',
        args: ['compose', '-p', `p311demo_${id}`, '-f', config.COMPOSE_FILE, ...actionArgs],
        env: {
            ...process.env,
            DEMO_PORT: String(port),
            DEMO_BACKEND_PORT: String(config.BACKEND_BASE + offset),
            DEMO_FRONTEND_PORT: String(config.FRONTEND_BASE + offset),
            GOOGLE_CLOUD_PROJECT: config.GOOGLE_CLOUD_PROJECT,
            GOOGLE_VERTEX_PROJECT: config.GOOGLE_VERTEX_PROJECT,
            GOOGLE_VERTEX_LOCATION: config.GOOGLE_VERTEX_LOCATION,
        },
    };
}

export function caddyReloadInvocation(config) {
    return {
        file: 'docker',
        args: ['exec', config.CADDY_CONTAINER, 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile'],
    };
}

export function generateDemoSubdomains(registry, baseDomain) {
    const blocks = [];
    for (const [id, inst] of Object.entries(registry)) {
        if (!validateId(id) || !validatePort(inst.port)) continue;
        if (inst.status === 'ready' || inst.status === 'booting') {
            blocks.push(`# Demo: ${id} (${sanitizeTownName(inst.townName)})`);
            blocks.push(`demo-${id}.${baseDomain} {`);
            blocks.push(`    reverse_proxy host.docker.internal:${inst.port}`);
            blocks.push(`}`);
            blocks.push('');
        }
    }
    return blocks.join('\n');
}
