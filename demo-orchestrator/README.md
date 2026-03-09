# Demo Orchestrator

Spins up **real, ephemeral Pinpoint 311 instances** for live demos on the marketing website.

## How It Works

1. Prospect clicks "Try Live Demo" on the marketing site
2. They enter their town name → orchestrator creates a full Pinpoint 311 stack (PostGIS + Redis + Backend + Frontend + Caddy)
3. In ~60 seconds, they're redirected to a real, fully functional instance pre-configured with their town name
4. Instance auto-destroys after 24 hours

## Quick Start

```bash
# On your demo server (needs Docker installed)
cd demo-orchestrator
npm install
node server.js
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3311` | Orchestrator API port |
| `MAX_INSTANCES` | `3` | Max concurrent demo instances |
| `DEMO_TTL_HOURS` | `24` | Hours before auto-cleanup |
| `BASE_PORT` | `9200` | Starting port for demo Caddy proxies |
| `DEMO_HOST` | `localhost` | Hostname for demo URLs |
| `GOOGLE_CLOUD_PROJECT` | — | Passed to demo instances for AI features |
| `GOOGLE_VERTEX_PROJECT` | — | Passed to demo instances for AI features |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/demo/create` | Create a new demo (body: `{ "townName": "Springfield, IL" }`) |
| `GET` | `/api/demo/:id/status` | Poll instance status (starting → booting → ready) |
| `DELETE` | `/api/demo/:id` | Destroy an instance |
| `GET` | `/api/demo/instances` | List all active instances |
| `GET` | `/api/demo/health` | Orchestrator health check |

## Server Requirements

- Docker + Docker Compose v2
- ~2GB RAM per concurrent demo instance
- Recommended: 8GB RAM server for 3 concurrent demos
