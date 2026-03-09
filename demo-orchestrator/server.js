import express from 'express';
import cors from 'cors';
import { execSync, exec } from 'child_process';
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

// ====== Configuration ======
const CONFIG = {
    MAX_INSTANCES: parseInt(process.env.MAX_INSTANCES || '3'),
    TTL_HOURS: parseInt(process.env.DEMO_TTL_HOURS || '24'),
    BASE_PORT: parseInt(process.env.BASE_PORT || '9200'),
    BACKEND_BASE: parseInt(process.env.BACKEND_BASE || '9000'),
    FRONTEND_BASE: parseInt(process.env.FRONTEND_BASE || '9100'),
    HOST: process.env.DEMO_HOST || 'localhost',
    PUBLIC_DOMAIN: process.env.PUBLIC_DOMAIN || 'pinpoint311.org',
    BASE_DOMAIN: process.env.BASE_DOMAIN || 'pinpoint311.org',
    DATA_DIR: join(__dirname, 'data'),
    COMPOSE_FILE: join(__dirname, 'docker-compose-demo.yml'),
    // Path to the MAIN production Caddyfile (to add demo routes)
    CADDYFILE_PATH: process.env.CADDYFILE_PATH || '/home/ubuntu/WWF-Open-Source-311-Template/Caddyfile',
    CADDY_CONTAINER: process.env.CADDY_CONTAINER || 'wwf-open-source-311-template-caddy-1',
    // API keys
    GOOGLE_CLOUD_PROJECT: process.env.GOOGLE_CLOUD_PROJECT || '',
    GOOGLE_VERTEX_PROJECT: process.env.GOOGLE_VERTEX_PROJECT || '',
    GOOGLE_VERTEX_LOCATION: process.env.GOOGLE_VERTEX_LOCATION || 'us-central1',
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
    // Short IDs for cleaner URLs
    return Math.random().toString(36).slice(2, 8);
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
    return new Promise((resolve, reject) => {
        const cmd = composeCmd(id, port, 'up -d --pull missing');
        console.log(`[${id}] Spinning up on port ${port}...`);
        exec(cmd, { timeout: 180000 }, (err, stdout, stderr) => {
            if (err) {
                console.error(`[${id}] Failed to start:`, stderr);
                reject(new Error(`Failed to start instance: ${stderr}`));
            } else {
                console.log(`[${id}] Started successfully`);
                resolve();
            }
        });
    });
}

async function tearDown(id, port) {
    return new Promise((resolve) => {
        const cmd = composeCmd(id, port, 'down -v --remove-orphans');
        console.log(`[${id}] Tearing down...`);
        exec(cmd, { timeout: 60000 }, (err) => {
            if (err) console.error(`[${id}] Teardown warning:`, err.message);
            else console.log(`[${id}] Torn down successfully`);
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
        const loginRes = await fetch(`${baseUrl}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'username=admin&password=DemoAdmin311!',
        });
        if (!loginRes.ok) {
            console.error(`[seed] Login failed: ${loginRes.status}`);
            return;
        }
        const { access_token } = await loginRes.json();
        const auth = { 'Authorization': `Bearer ${access_token}`, 'Content-Type': 'application/json' };

        await fetch(`${baseUrl}/settings`, {
            method: 'PUT', headers: auth,
            body: JSON.stringify({ municipality_name: townName }),
        });

        console.log(`[seed] Configured municipality: ${townName}`);
    } catch (err) {
        console.error(`[seed] Error:`, err.message);
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
            blocks.push(`    reverse_proxy localhost:${port}`);
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
        exec(`docker exec ${CONFIG.CADDY_CONTAINER} caddy reload --config /etc/caddy/Caddyfile`, (err) => {
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
    const registry = loadRegistry();
    const inst = registry[req.params.id];
    if (!inst) return res.status(404).json({ error: 'Instance not found' });

    const ttlMs = CONFIG.TTL_HOURS * 3600 * 1000;
    const expiresAt = new Date(inst.created + ttlMs).toISOString();
    const timeRemaining = Math.max(0, inst.created + ttlMs - Date.now());

    res.json({
        id: req.params.id,
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
    const registry = loadRegistry();
    const inst = registry[req.params.id];
    if (!inst) return res.status(404).json({ error: 'Instance not found' });

    await tearDown(req.params.id, inst.port);
    delete registry[req.params.id];
    saveRegistry(registry);
    updateCaddyfile(registry);

    res.json({ status: 'destroyed', id: req.params.id });
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
