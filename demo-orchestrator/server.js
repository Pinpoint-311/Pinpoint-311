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

// ====== Configuration ======
const CONFIG = {
    MAX_INSTANCES: parseInt(process.env.MAX_INSTANCES || '3'),
    TTL_HOURS: parseInt(process.env.DEMO_TTL_HOURS || '24'),
    BASE_PORT: parseInt(process.env.BASE_PORT || '9200'),      // Caddy combined port
    BACKEND_BASE: parseInt(process.env.BACKEND_BASE || '9000'), // Direct backend port
    FRONTEND_BASE: parseInt(process.env.FRONTEND_BASE || '9100'), // Direct frontend port
    HOST: process.env.DEMO_HOST || 'localhost',
    DATA_DIR: join(__dirname, 'data'),
    COMPOSE_FILE: join(__dirname, 'docker-compose-demo.yml'),
    // API keys passed through to demo instances
    GOOGLE_CLOUD_PROJECT: process.env.GOOGLE_CLOUD_PROJECT || '',
    GOOGLE_VERTEX_PROJECT: process.env.GOOGLE_VERTEX_PROJECT || '',
    GOOGLE_VERTEX_LOCATION: process.env.GOOGLE_VERTEX_LOCATION || 'us-central1',
};

// Ensure data directory exists
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
    return 'demo_' + Math.random().toString(36).slice(2, 8) + '_' + Date.now().toString(36);
}

function findAvailablePort(registry) {
    const usedPorts = new Set(Object.values(registry).map(i => i.port));
    for (let p = CONFIG.BASE_PORT; p < CONFIG.BASE_PORT + 100; p++) {
        if (!usedPorts.has(p)) return p;
    }
    throw new Error('No available ports');
}

// ====== Docker Compose Helpers ======
function projectName(id) { return `p311demo_${id.replace(/[^a-z0-9_]/g, '')}`; }

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
        exec(cmd, { timeout: 120000 }, (err, stdout, stderr) => {
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

async function waitForHealthy(port, maxWaitSec = 90) {
    const backendPort = CONFIG.BACKEND_BASE + (port - CONFIG.BASE_PORT);
    const start = Date.now();
    while (Date.now() - start < maxWaitSec * 1000) {
        try {
            const res = await fetch(`http://localhost:${backendPort}/api/health`);
            if (res.ok) return true;
        } catch { }
        await new Promise(r => setTimeout(r, 3000));
    }
    return false;
}

async function seedDemoData(port, townName) {
    const backendPort = CONFIG.BACKEND_BASE + (port - CONFIG.BASE_PORT);
    const baseUrl = `http://localhost:${backendPort}/api`;

    try {
        // 1. Login as admin to get token
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

        // 2. Update municipality name in settings
        await fetch(`${baseUrl}/settings`, {
            method: 'PUT', headers: auth,
            body: JSON.stringify({ municipality_name: townName }),
        });

        console.log(`[seed] Configured municipality: ${townName}`);
    } catch (err) {
        console.error(`[seed] Error:`, err.message);
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
        console.log(`[cleanup] Removed ${cleaned} expired instances`);
    }
}

// Run cleanup every 15 minutes
cron.schedule('*/15 * * * *', () => {
    console.log('[cron] Running cleanup...');
    cleanupExpired().catch(err => console.error('[cron] Cleanup error:', err));
});

// ====== API Routes ======

// Create a new demo instance
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

        // Register instance immediately
        registry[id] = {
            created: Date.now(),
            port,
            townName: townName.trim(),
            status: 'starting',
        };
        saveRegistry(registry);

        // Respond immediately with instance ID — client will poll for status
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
                registry[id].url = `http://${CONFIG.HOST}:${port}`;
                registry[id].credentials = {
                    username: 'admin',
                    password: 'DemoAdmin311!',
                };
            } else {
                registry[id].status = 'failed';
                registry[id].error = 'Backend did not become healthy in time';
                // Clean up failed instance
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

// Check instance status
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

// Manually destroy an instance
app.delete('/api/demo/:id', async (req, res) => {
    const registry = loadRegistry();
    const inst = registry[req.params.id];
    if (!inst) return res.status(404).json({ error: 'Instance not found' });

    await tearDown(req.params.id, inst.port);
    delete registry[req.params.id];
    saveRegistry(registry);

    res.json({ status: 'destroyed', id: req.params.id });
});

// List all active instances (admin endpoint)
app.get('/api/demo/instances', (req, res) => {
    const registry = loadRegistry();
    const instances = Object.entries(registry).map(([id, inst]) => ({
        id,
        ...inst,
        createdAt: new Date(inst.created).toISOString(),
    }));
    res.json({ count: instances.length, maxInstances: CONFIG.MAX_INSTANCES, instances });
});

// Health check
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
    console.log(`   Base port: ${CONFIG.BASE_PORT}`);

    // Run cleanup on startup
    cleanupExpired().catch(err => console.error('Startup cleanup error:', err));
});
