# System Architecture

This document provides a visual overview of Pinpoint 311's architecture for emergency contractors and new maintainers.

## Service Dependencies

```mermaid
graph TB
    subgraph "User Facing"
        R[Resident Portal]
        S[Staff Portal]
        A[Admin Console]
    end
    
    subgraph "Frontend Container"
        F[React Frontend<br/>Vite + TypeScript]
    end
    
    subgraph "Backend Container"
        B[FastAPI Backend<br/>Python 3.11+]
        C[Celery Workers]
    end
    
    subgraph "Data Layer"
        DB[(PostgreSQL 15<br/>+ PostGIS)]
        RD[(Redis)]
    end
    
    subgraph "External Services"
        AUTH0[Auth0 SSO]
        GCP[Google Cloud<br/>KMS / Vertex AI]
        S3[S3-Compatible<br/>Backup Storage]
    end
    
    subgraph "Reverse Proxy"
        CAD[Caddy<br/>Auto HTTPS]
    end
    
    R --> CAD
    S --> CAD
    A --> CAD
    CAD --> F
    CAD --> B
    F --> B
    B --> DB
    B --> RD
    B --> AUTH0
    B --> GCP
    B --> S3
    C --> DB
    C --> RD
```

## Data Flow

```mermaid
sequenceDiagram
    participant Resident
    participant Frontend
    participant Backend
    participant Database
    participant AI as Vertex AI
    
    Resident->>Frontend: Submit Request
    Frontend->>Backend: POST /api/requests
    Backend->>AI: Analyze (async)
    Backend->>Database: Store Request
    Backend-->>Frontend: Request ID
    AI-->>Backend: Priority Score
    Backend->>Database: Update AI Analysis
    Frontend-->>Resident: Confirmation + Magic Link
```

## Network Topology

```mermaid
graph LR
    subgraph "Public Internet"
        U[Users]
    end
    
    subgraph "DMZ - Port 443"
        CAD[Caddy Reverse Proxy]
    end
    
    subgraph "Docker Network - Internal Only"
        F[Frontend :80]
        B[Backend :8000]
        DB[PostgreSQL :5432]
        RD[Redis :6379]
    end
    
    U -->|HTTPS 443| CAD
    CAD -->|HTTP| F
    CAD -->|HTTP| B
    B --> DB
    B --> RD
```

## Container Restart Order

If manual restarts are needed:

| Order | Container | Command | Notes |
|-------|-----------|---------|-------|
| 1 | Database | `docker-compose restart db` | Only if absolutely needed |
| 2 | Redis | `docker-compose restart redis` | Cache will rebuild |
| 3 | Backend | `docker-compose restart backend` | API server |
| 4 | Frontend | `docker-compose restart frontend` | Static files |
| 5 | Caddy | `docker-compose restart caddy` | Renews certs |

## Key File Locations

| Component | Path | Purpose |
|-----------|------|---------|
| Docker Config | `/docker-compose.yml` | Container orchestration |
| Backend Code | `/backend/app/` | FastAPI application |
| Frontend Code | `/frontend/src/` | React application |
| API Routes | `/backend/app/api/` | Endpoint definitions |
| Database Models | `/backend/app/models/` | SQLAlchemy models |
| Migrations | `/backend/alembic/` | Schema migrations |

## Emergency Quick Reference

### Check All Services
```bash
docker-compose ps
```

### View Logs
```bash
docker-compose logs --tail=100 backend
docker-compose logs --tail=100 frontend
```

### Restart Everything (Safe)
```bash
docker-compose restart backend frontend redis caddy
```

### Database Connection
```bash
docker exec -it wwf-311-fix-db-1 psql -U postgres -d pinpoint311
```

### Create Backup
```bash
curl -X POST https://your-domain/api/system/backups/create \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

*Last Updated: February 2026*
