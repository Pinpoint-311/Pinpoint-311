#!/bin/bash
# Reset the Pinpoint 311 demo database
# Run daily via cron: 0 3 * * * /home/ubuntu/WWF-Open-Source-311-Template/scripts/reset-demo.sh

set -e

COMPOSE_DIR="/home/ubuntu/WWF-Open-Source-311-Template"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.demo.yml"

echo "[$(date)] Starting demo reset..."

# Stop demo stack
cd "$COMPOSE_DIR"
docker compose -f "$COMPOSE_FILE" down demo-backend demo-worker 2>/dev/null || true

# Wipe and recreate database
docker compose -f "$COMPOSE_FILE" exec -T demo-db psql -U demo -d demo_db -c "
  DROP SCHEMA public CASCADE;
  CREATE SCHEMA public;
  GRANT ALL ON SCHEMA public TO demo;
" 2>/dev/null || true

# Restart backend (will re-run migrations and seed)
docker compose -f "$COMPOSE_FILE" up -d demo-backend demo-worker

echo "[$(date)] Demo reset complete."
