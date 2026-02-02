# Alembic Migration Environment

This directory contains Alembic database migration scripts.

## Usage

### Generate a new migration after model changes:
```bash
docker compose exec backend alembic revision --autogenerate -m "description of changes"
```

### Apply pending migrations:
```bash
docker compose exec backend alembic upgrade head
```

### Rollback one migration:
```bash
docker compose exec backend alembic downgrade -1
```

### View migration history:
```bash
docker compose exec backend alembic history
```

### Show current revision:
```bash
docker compose exec backend alembic current
```

## Notes

- PostGIS and Tiger geocoder tables are excluded from autogenerate
- Always review generated migrations before applying
- Test migrations in development before deploying to production
