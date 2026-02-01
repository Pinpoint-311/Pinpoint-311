# Disaster Recovery Runbook

This document outlines procedures for backup, recovery, and disaster response for the Pinpoint 311 system.

## Table of Contents
1. [Backup Overview](#backup-overview)
2. [Manual Backup Procedure](#manual-backup-procedure)
3. [Disaster Recovery Drill](#disaster-recovery-drill)
4. [Emergency Restore Procedure](#emergency-restore-procedure)
5. [Contact Information](#contact-information)

---

## Backup Overview

### Automated Backups
- **Frequency**: Configurable via Admin Console
- **Storage**: S3-compatible storage (AWS S3, Backblaze B2, etc.)
- **Retention**: Based on state retention policy (default: 7 years for NJ)

### What's Backed Up
| Component | Backed Up | Method |
|-----------|-----------|--------|
| PostgreSQL Database | ✅ | `pg_dump` compressed |
| Uploaded Files (S3) | ✅ | Separate S3 bucket backup |
| Configuration | ✅ | Environment variables in Secret Manager |
| Docker Images | ✅ | GHCR (versioned with SHA) |

### Deployment-Triggered Backups

The **Version Switcher** in the Admin Console automatically creates a database backup before every deployment:

| Trigger | Location | Retention |
|---------|----------|-----------|
| Version deployment | `/project/backups/` | Preserved for recovery |
| Format | `pg_dump` compressed SQL | Timestamped filename |

These backups provide an additional recovery point specifically tied to version changes, enabling rollback to the exact database state before a deployment.

### What's NOT Backed Up (Ephemeral)
- Redis cache (rebuilds automatically)
- Session tokens (users re-login)
- Celery task queue (tasks re-queue)

---

## Manual Backup Procedure

### Via Admin Console
1. Navigate to **Admin Console → System → Backups**
2. Click **"Create Backup Now"**
3. Wait for confirmation (typically 1-5 minutes)
4. Verify backup appears in backup list

### Via API
```bash
# Trigger backup
curl -X POST https://311.westwindsorforward.org/api/system/backups/create \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# List backups
curl https://311.westwindsorforward.org/api/system/backups \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Via SSH (Emergency)
```bash
# SSH to production server
ssh ubuntu@132.226.32.116

# Enter the backend container
docker exec -it wwf-311-fix-backend-1 bash

# Manual pg_dump
pg_dump -h db -U postgres pinpoint311 | gzip > /tmp/emergency_backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Copy out of container
docker cp wwf-311-fix-backend-1:/tmp/emergency_backup_*.sql.gz ./
```

---

## Disaster Recovery Drill

**Recommended Frequency**: Quarterly

### Pre-Drill Checklist
- [ ] Schedule 2-hour maintenance window
- [ ] Notify stakeholders
- [ ] Ensure backup is less than 24 hours old
- [ ] Have SSH access credentials ready
- [ ] Have database password available

### Drill Procedure

#### Step 1: Create Fresh Backup (5 min)
```bash
# Via Admin Console or API
curl -X POST https://311.westwindsorforward.org/api/system/backups/create \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### Step 2: Spin Up Test Environment (15 min)
```bash
# Clone repo on a test server
git clone https://github.com/WestWindsorForward/WWF-Open-Source-311-Template.git
cd WWF-Open-Source-311-Template

# Copy production .env (with different DB name)
cp /path/to/production/.env .env
sed -i 's/pinpoint311/pinpoint311_dr_test/' .env

# Start services
docker compose up -d
```

#### Step 3: Download Backup from S3 (5 min)
```bash
# List available backups
aws s3 ls s3://your-backup-bucket/backups/

# Download latest backup
aws s3 cp s3://your-backup-bucket/backups/latest.sql.gz ./restore.sql.gz
```

#### Step 4: Restore Database (10 min)
```bash
# Stop backend to prevent writes
docker compose stop backend celery_worker

# Restore to test database
gunzip -c restore.sql.gz | docker exec -i wwf-311-fix-db-1 \
  psql -U postgres -d pinpoint311_dr_test

# Restart services
docker compose up -d
```

#### Step 5: Verify Data Integrity (15 min)
- [ ] Login to Staff Dashboard works
- [ ] Recent requests are visible
- [ ] Request count matches production
- [ ] Audit logs are intact
- [ ] Service categories load correctly
- [ ] Map layers display properly

#### Step 6: Document Results
```markdown
## DR Drill Results - [DATE]

**Backup Used**: [filename]
**Backup Age**: [hours since backup]
**Restore Time**: [minutes]
**Data Verified**: [yes/no]
**Issues Found**: [list any issues]
**Conducted By**: [name]
```

#### Step 7: Cleanup
```bash
# Destroy test environment
docker compose down -v
cd ..
rm -rf WWF-Open-Source-311-Template
```

---

## Emergency Restore Procedure

### Scenario: Production Database Corrupted/Lost

**RTO (Recovery Time Objective)**: 1 hour
**RPO (Recovery Point Objective)**: 24 hours (based on backup frequency)

#### Immediate Actions
1. **Assess Damage** - Is this corruption or hardware failure?
2. **Notify Stakeholders** - Email/call department heads
3. **Enable Maintenance Mode** - Show friendly error page

#### Restore Steps

```bash
# 1. SSH to production
ssh ubuntu@132.226.32.116
cd /path/to/app

# 2. Stop all services
docker compose down

# 3. Download latest backup
aws s3 cp s3://your-backup-bucket/backups/latest.sql.gz ./restore.sql.gz

# 4. Start only database
docker compose up -d db
sleep 30

# 5. Drop and recreate database (DESTRUCTIVE)
docker exec -i wwf-311-fix-db-1 psql -U postgres -c "DROP DATABASE IF EXISTS pinpoint311;"
docker exec -i wwf-311-fix-db-1 psql -U postgres -c "CREATE DATABASE pinpoint311;"

# 6. Restore backup
gunzip -c restore.sql.gz | docker exec -i wwf-311-fix-db-1 psql -U postgres -d pinpoint311

# 7. Start all services
docker compose up -d

# 8. Verify system health
curl https://311.westwindsorforward.org/api/health
```

#### Post-Recovery
1. Verify all data is intact
2. Check audit logs for last entries before incident
3. Document what was lost (if any)
4. Conduct root cause analysis
5. Update this runbook if needed

---

## Contact Information

| Role | Name | Contact |
|------|------|---------|
| System Admin | [TBD] | [TBD] |
| Database Admin | [TBD] | [TBD] |
| On-Call Engineer | [TBD] | [TBD] |

### Vendor Escalation Directory

> These contacts can help even if the original developer is unavailable.

#### Identity & Authentication (Auth0)
| Resource | URL/Contact |
|----------|-------------|
| Auth0 Status | https://status.auth0.com/ |
| Auth0 Support | https://support.auth0.com/ (paid plans) |
| Auth0 Community | https://community.auth0.com/ |

#### Google Cloud Platform
| Resource | URL/Contact |
|----------|-------------|
| GCP Status | https://status.cloud.google.com/ |
| GCP Console | https://console.cloud.google.com/ |
| Vertex AI Docs | https://cloud.google.com/vertex-ai/docs |

#### PostgreSQL Emergency Help
| Resource | URL/Contact |
|----------|-------------|
| PostgreSQL Wiki | https://wiki.postgresql.org/wiki/Emergency_Recovery |
| Crunchy Data | https://www.crunchydata.com/support |
| Freelance DBAs | Upwork, Toptal (search "PostgreSQL DBA emergency") |

#### Docker/DevOps Contractors
| Resource | Best For |
|----------|----------|
| **Upwork** | Quick fixes, hourly work |
| **Toptal** | Senior DevOps engineers |
| **Fiverr Pro** | Small configuration tasks |

### Emergency Contractor Onboarding Checklist

Before giving a contractor access:
- [ ] Review [ARCHITECTURE.md](./ARCHITECTURE.md) with them
- [ ] Provide read-only access first
- [ ] Create temporary admin credentials (revoke after)
- [ ] Monitor actions in audit logs

### External Status Pages
- **Auth0 Status**: https://status.auth0.com/
- **Sentry Status**: https://status.sentry.io/
- **GitHub Status**: https://www.githubstatus.com/
- **Google Cloud Status**: https://status.cloud.google.com/

---

*Last Updated: February 2026*
*Review Schedule: Quarterly*
