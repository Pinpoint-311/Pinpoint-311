import express from 'express';
import cors from 'cors';
import { exec } from 'child_process';
import crypto from 'crypto';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import cron from 'node-cron';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(cors());
app.use(express.json());

// Catch unhandled promise rejections
process.on('unhandledRejection', (reason, promise) => {
    console.error('[FATAL] Unhandled rejection:', reason);
});

// ====== Security Helpers ======
function sanitizeForLog(str) {
    if (typeof str !== 'string') return String(str);
    return str.replace(/[\r\n\t]/g, ' ').replace(/[\x00-\x1f\x7f]/g, '').slice(0, 200);
}

function validateId(id) {
    return typeof id === 'string' && /^[a-z0-9]{4,8}$/.test(id);
}

function validateConfigValue(value, name) {
    if (typeof value === 'string' && /[;&|`$(){}\n\r]/.test(value)) {
        throw new Error(`Invalid characters in config value: ${name}`);
    }
    return value;
}

// ====== Configuration ======
const CONFIG = {
    MAX_INSTANCES: parseInt(process.env.MAX_INSTANCES || '3'),
    TTL_HOURS: parseInt(process.env.DEMO_TTL_HOURS || '24'),
    BASE_PORT: parseInt(process.env.BASE_PORT || '9200'),
    BACKEND_BASE: parseInt(process.env.BACKEND_BASE || '9000'),
    FRONTEND_BASE: parseInt(process.env.FRONTEND_BASE || '9100'),
    HOST: validateConfigValue(process.env.DEMO_HOST || 'localhost', 'DEMO_HOST'),
    PUBLIC_DOMAIN: validateConfigValue(process.env.PUBLIC_DOMAIN || 'pinpoint311.org', 'PUBLIC_DOMAIN'),
    BASE_DOMAIN: validateConfigValue(process.env.BASE_DOMAIN || 'pinpoint311.org', 'BASE_DOMAIN'),
    DATA_DIR: join(__dirname, 'data'),
    COMPOSE_FILE: join(__dirname, 'docker-compose-demo.yml'),
    // Path to the MAIN production Caddyfile (to add demo routes)
    CADDYFILE_PATH: validateConfigValue(process.env.CADDYFILE_PATH || '/home/ubuntu/WWF-Open-Source-311-Template/Caddyfile', 'CADDYFILE_PATH'),
    CADDY_CONTAINER: validateConfigValue(process.env.CADDY_CONTAINER || 'wwf-open-source-311-template-caddy-1', 'CADDY_CONTAINER'),
    // API keys
    GOOGLE_CLOUD_PROJECT: validateConfigValue(process.env.GOOGLE_CLOUD_PROJECT || '', 'GOOGLE_CLOUD_PROJECT'),
    GOOGLE_VERTEX_PROJECT: validateConfigValue(process.env.GOOGLE_VERTEX_PROJECT || '', 'GOOGLE_VERTEX_PROJECT'),
    GOOGLE_VERTEX_LOCATION: validateConfigValue(process.env.GOOGLE_VERTEX_LOCATION || 'us-central1', 'GOOGLE_VERTEX_LOCATION'),
};

if (!existsSync(CONFIG.DATA_DIR)) mkdirSync(CONFIG.DATA_DIR, { recursive: true });

// ====== Instance Registry ======
const REGISTRY_FILE = join(CONFIG.DATA_DIR, 'instances.json');

function loadRegistry() {
    if (!existsSync(REGISTRY_FILE)) return {};
    try { return JSON.parse(readFileSync(REGISTRY_FILE, 'utf8')); } catch { return {}; }
}

function saveRegistry(r) {
    writeFileSync(REGISTRY_FILE, JSON.stringify(r, null, 2));
}

function generateId() {
    // Cryptographically random short IDs for cleaner URLs
    const bytes = new Uint8Array(6);
    crypto.getRandomValues(bytes);
    return Array.from(bytes).map(b => b.toString(36).padStart(2, '0')).join('').slice(0, 8);
}

function findAvailablePort(registry) {
    const usedPorts = new Set(Object.values(registry).map(i => i.port));
    for (let p = CONFIG.BASE_PORT; p < CONFIG.BASE_PORT + 100; p++) {
        if (!usedPorts.has(p)) return p;
    }
    throw new Error('No available ports');
}

// ====== Docker Compose Helpers ======
function projectName(id) { return `p311demo_${id}`; }

function composeCmd(id, port, action) {
    const backendPort = CONFIG.BACKEND_BASE + (port - CONFIG.BASE_PORT);
    const frontendPort = CONFIG.FRONTEND_BASE + (port - CONFIG.BASE_PORT);
    const env = [
        `DEMO_PORT=${port}`,
        `DEMO_BACKEND_PORT=${backendPort}`,
        `DEMO_FRONTEND_PORT=${frontendPort}`,
        `GOOGLE_CLOUD_PROJECT=${CONFIG.GOOGLE_CLOUD_PROJECT}`,
        `GOOGLE_VERTEX_PROJECT=${CONFIG.GOOGLE_VERTEX_PROJECT}`,
        `GOOGLE_VERTEX_LOCATION=${CONFIG.GOOGLE_VERTEX_LOCATION}`,
    ].join(' ');
    return `${env} docker compose -p ${projectName(id)} -f ${CONFIG.COMPOSE_FILE} ${action}`;
}

async function spinUp(id, port) {
    if (!validateId(id)) throw new Error('Invalid instance ID');
    if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid port');
    return new Promise((resolve, reject) => {
        const cmd = composeCmd(id, port, 'up -d --pull missing');
        console.log('[%s] Spinning up on port %d...', sanitizeForLog(id), port);
        exec(cmd, { timeout: 180000 }, (err, stdout, stderr) => {
            if (err) {
                console.error('[%s] Failed to start: %s', sanitizeForLog(id), sanitizeForLog(stderr));
                reject(new Error('Failed to start instance'));
            } else {
                console.log('[%s] Started successfully', sanitizeForLog(id));
                resolve();
            }
        });
    });
}

async function tearDown(id, port) {
    if (!validateId(id)) throw new Error('Invalid instance ID');
    if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid port');
    return new Promise((resolve) => {
        const cmd = composeCmd(id, port, 'down -v --remove-orphans');
        console.log('[%s] Tearing down...', sanitizeForLog(id));
        exec(cmd, { timeout: 60000 }, (err) => {
            if (err) console.error('[%s] Teardown warning: %s', sanitizeForLog(id), sanitizeForLog(err.message));
            else console.log('[%s] Torn down successfully', sanitizeForLog(id));
            resolve();
        });
    });
}

async function waitForHealthy(port, maxWaitSec = 120) {
    const backendPort = CONFIG.BACKEND_BASE + (port - CONFIG.BASE_PORT);
    const start = Date.now();
    console.log(`[health] Polling http://localhost:${backendPort}/api/health (max ${maxWaitSec}s)...`);
    let attempt = 0;
    while (Date.now() - start < maxWaitSec * 1000) {
        attempt++;
        try {
            const res = await fetch(`http://localhost:${backendPort}/api/health`);
            if (res.ok) {
                console.log(`[health] Backend healthy after ${attempt} attempts`);
                return true;
            }
            console.log(`[health] Attempt ${attempt}: status ${res.status}`);
        } catch (err) {
            if (attempt % 5 === 0) console.log(`[health] Attempt ${attempt}: ${err.message}`);
        }
        await new Promise(r => setTimeout(r, 3000));
    }
    console.error(`[health] Timed out after ${maxWaitSec}s (${attempt} attempts)`);
    return false;
}

async function seedDemoData(port, townName) {
    const backendPort = CONFIG.BACKEND_BASE + (port - CONFIG.BASE_PORT);
    const baseUrl = `http://localhost:${backendPort}/api`;

    try {
        // Step 1: Generate a bootstrap token (only works when Auth0 is NOT configured)
        const bootstrapRes = await fetch(`${baseUrl}/auth/bootstrap`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!bootstrapRes.ok) {
            console.error(`[seed] Bootstrap failed: ${bootstrapRes.status}`);
            return;
        }
        const bootstrapData = await bootstrapRes.json();
        const bootstrapToken = bootstrapData.token;

        // Step 2: Use the bootstrap token to get a JWT
        // The GET endpoint returns HTML that sets localStorage, but we can extract the JWT
        // by calling the endpoint and parsing the response
        const tokenRes = await fetch(`${baseUrl}/auth/bootstrap/${bootstrapToken}`, {
            method: 'GET',
            redirect: 'manual',  // Don't follow redirects
        });

        // The response is HTML with the JWT embedded — extract it
        const html = await tokenRes.text();
        const tokenMatch = html.match(/localStorage\.setItem\('token',\s*'([^']+)'\)/);
        if (!tokenMatch) {
            console.error(`[seed] Could not extract JWT from bootstrap response`);
            return;
        }
        const access_token = tokenMatch[1];
        const auth = { 'Authorization': `Bearer ${access_token}`, 'Content-Type': 'application/json' };

        // Step 3: Set municipality name
        await fetch(`${baseUrl}/settings`, {
            method: 'PUT', headers: auth,
            body: JSON.stringify({ municipality_name: townName }),
        });

        console.log('[seed] Configured municipality: %s', sanitizeForLog(townName));
    } catch (err) {
        console.error('[seed] Error: %s', sanitizeForLog(err.message));
    }
}

// ====== Dynamic Caddy Subdomain Management ======
// Each demo instance gets its own subdomain: demo-{id}.pinpoint311.org
// Cloudflare DNS-only (grey cloud) — Caddy gets Let's Encrypt certs directly

const CADDY_MARKER_START = '# === DEMO SUBDOMAINS START ===';
const CADDY_MARKER_END = '# === DEMO SUBDOMAINS END ===';

function generateDemoSubdomains(registry) {
    const blocks = [];
    for (const [id, inst] of Object.entries(registry)) {
        if (inst.status === 'ready' || inst.status === 'booting') {
            const port = inst.port;
            const subdomain = `demo-${id}.${CONFIG.BASE_DOMAIN}`;
            blocks.push(`# Demo: ${id} (${inst.townName})`);
            blocks.push(`${subdomain} {`);
            blocks.push(`    reverse_proxy host.docker.internal:${port}`);
            blocks.push(`}`);
            blocks.push('');
        }
    }
    return blocks.join('\n');
}

function updateCaddyfile(registry) {
    try {
        let content = readFileSync(CONFIG.CADDYFILE_PATH, 'utf8');
        const subdomains = generateDemoSubdomains(registry);
        const demoBlock = `\n${CADDY_MARKER_START}\n${subdomains}\n${CADDY_MARKER_END}`;

        if (content.includes(CADDY_MARKER_START)) {
            const re = new RegExp(`\\n?${CADDY_MARKER_START}[\\s\\S]*?${CADDY_MARKER_END}`, 'g');
            content = content.replace(re, demoBlock);
        } else {
            // Append subdomain blocks at the END of the Caddyfile
            content += demoBlock;
        }

        writeFileSync(CONFIG.CADDYFILE_PATH, content);
        const count = Object.values(registry).filter(i => i.status === 'ready' || i.status === 'booting').length;
        console.log(`[caddy] Updated Caddyfile with ${count} demo subdomain(s)`);

        // Reload Caddy
        exec(`docker exec ${CONFIG.CADDY_CONTAINER} caddy reload --config /etc/caddy/Caddyfile`, { timeout: 15000 }, (err) => {
            if (err) console.error('[caddy] Reload warning:', err.message);
            else console.log('[caddy] Reloaded successfully');
        });
    } catch (err) {
        console.error('[caddy] Failed to update Caddyfile:', err.message);
    }
}

// ====== Cleanup Job ======
async function cleanupExpired() {
    const registry = loadRegistry();
    const now = Date.now();
    const ttlMs = CONFIG.TTL_HOURS * 3600 * 1000;
    let cleaned = 0;

    for (const [id, inst] of Object.entries(registry)) {
        if (now - inst.created > ttlMs) {
            console.log(`[cleanup] Instance ${id} expired (created ${new Date(inst.created).toISOString()})`);
            await tearDown(id, inst.port);
            delete registry[id];
            cleaned++;
        }
    }

    if (cleaned > 0) {
        saveRegistry(registry);
        updateCaddyfile(registry);
        console.log(`[cleanup] Removed ${cleaned} expired instances`);
    }
}

// ====== Recovery: Fix instances stuck in 'booting' or 'starting' ======
async function recoverStuckInstances() {
    const registry = loadRegistry();
    let recovered = 0;

    for (const [id, inst] of Object.entries(registry)) {
        if (inst.status === 'booting' || inst.status === 'starting') {
            const backendPort = CONFIG.BACKEND_BASE + (inst.port - CONFIG.BASE_PORT);
            console.log(`[recovery] Checking stuck instance ${id} (status: ${inst.status})...`);
            try {
                const res = await fetch(`http://localhost:${backendPort}/api/health`);
                if (res.ok) {
                    console.log(`[recovery] Instance ${id} backend is healthy — marking ready`);
                    await seedDemoData(inst.port, inst.townName);
                    registry[id].status = 'ready';
                    registry[id].url = `https://demo-${id}.${CONFIG.BASE_DOMAIN}`;
                    registry[id].credentials = { username: 'admin', password: 'DemoAdmin311!' };
                    recovered++;
                }
            } catch (err) {
                console.log(`[recovery] Instance ${id} not healthy yet: ${err.message}`);
            }
        }
    }

    if (recovered > 0) {
        saveRegistry(registry);
        updateCaddyfile(registry);
        console.log(`[recovery] Recovered ${recovered} stuck instances`);
    }
}

cron.schedule('*/2 * * * *', () => {
    recoverStuckInstances().catch(err => console.error('[cron] Recovery error:', err));
});

cron.schedule('*/15 * * * *', () => {
    console.log('[cron] Running cleanup...');
    cleanupExpired().catch(err => console.error('[cron] Cleanup error:', err));
});

// ====== API Routes ======

app.post('/api/demo/create', async (req, res) => {
    try {
        const { townName } = req.body;
        if (!townName || typeof townName !== 'string' || townName.trim().length < 2) {
            return res.status(400).json({ error: 'townName is required (min 2 characters)' });
        }

        const registry = loadRegistry();
        const activeCount = Object.keys(registry).length;

        if (activeCount >= CONFIG.MAX_INSTANCES) {
            return res.status(429).json({
                error: 'Maximum concurrent demos reached. Please try again later.',
                maxInstances: CONFIG.MAX_INSTANCES,
                activeCount,
            });
        }

        const id = generateId();
        const port = findAvailablePort(registry);

        registry[id] = {
            created: Date.now(),
            port,
            townName: townName.trim(),
            status: 'starting',
        };
        saveRegistry(registry);

        res.json({
            id,
            status: 'starting',
            message: 'Instance is being created. Poll /api/demo/:id/status for updates.',
        });

        // Spin up in background
        try {
            await spinUp(id, port);
            registry[id].status = 'booting';
            saveRegistry(registry);

            const healthy = await waitForHealthy(port);
            if (healthy) {
                await seedDemoData(port, townName.trim());
                registry[id].status = 'ready';
                // URL goes through the main Caddy proxy — no firewall issues!
                registry[id].url = `https://demo-${id}.${CONFIG.BASE_DOMAIN}`;
                registry[id].credentials = {
                    username: 'admin',
                    password: 'DemoAdmin311!',
                };
                // Update Caddy to route traffic to this instance
                updateCaddyfile(registry);
            } else {
                registry[id].status = 'failed';
                registry[id].error = 'Backend did not become healthy in time';
                await tearDown(id, port);
            }
        } catch (err) {
            registry[id].status = 'failed';
            registry[id].error = err.message;
            await tearDown(id, port).catch(() => { });
        }
        saveRegistry(registry);

    } catch (err) {
        console.error('Create error:', err);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.get('/api/demo/:id/status', (req, res) => {
    const id = req.params.id;
    if (!validateId(id)) return res.status(400).json({ error: 'Invalid instance ID' });
    const registry = loadRegistry();
    if (!Object.hasOwn(registry, id)) return res.status(404).json({ error: 'Instance not found' });
    const inst = registry[id];

    const ttlMs = CONFIG.TTL_HOURS * 3600 * 1000;
    const expiresAt = new Date(inst.created + ttlMs).toISOString();
    const timeRemaining = Math.max(0, inst.created + ttlMs - Date.now());

    res.json({
        id,
        status: inst.status,
        url: inst.url || null,
        credentials: inst.status === 'ready' ? inst.credentials : null,
        townName: inst.townName,
        createdAt: new Date(inst.created).toISOString(),
        expiresAt,
        timeRemainingMs: timeRemaining,
        error: inst.error || null,
    });
});

app.delete('/api/demo/:id', async (req, res) => {
    const id = req.params.id;
    if (!validateId(id)) return res.status(400).json({ error: 'Invalid instance ID' });
    const registry = loadRegistry();
    if (!Object.hasOwn(registry, id)) return res.status(404).json({ error: 'Instance not found' });
    const inst = registry[id];

    await tearDown(id, inst.port);
    delete registry[id];
    saveRegistry(registry);
    updateCaddyfile(registry);

    res.json({ status: 'destroyed', id });
});

app.get('/api/demo/instances', (req, res) => {
    const registry = loadRegistry();
    const instances = Object.entries(registry).map(([id, inst]) => ({
        id,
        ...inst,
        createdAt: new Date(inst.created).toISOString(),
    }));
    res.json({ count: instances.length, maxInstances: CONFIG.MAX_INSTANCES, instances });
});

app.get('/api/demo/health', (req, res) => {
    const registry = loadRegistry();
    res.json({
        status: 'ok',
        activeInstances: Object.keys(registry).length,
        maxInstances: CONFIG.MAX_INSTANCES,
    });
});

// ====== Start Server ======
const PORT = process.env.PORT || 3311;
app.listen(PORT, () => {
    console.log(`🚀 Pinpoint 311 Demo Orchestrator running on port ${PORT}`);
    console.log(`   Max instances: ${CONFIG.MAX_INSTANCES}`);
    console.log(`   TTL: ${CONFIG.TTL_HOURS} hours`);
    console.log(`   Public domain: ${CONFIG.PUBLIC_DOMAIN}`);
    cleanupExpired().catch(err => console.error('Startup cleanup error:', err));
    // Recover instances stuck in booting/starting from previous crash
    setTimeout(() => {
        recoverStuckInstances().catch(err => console.error('Startup recovery error:', err));
    }, 5000);
});
