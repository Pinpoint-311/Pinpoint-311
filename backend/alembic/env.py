from logging.config import fileConfig
import os
import sys

from sqlalchemy import create_engine, pool
from alembic import context

# Add the app to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import Base
from app.models import *  # Import all models to register them with Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Exclude PostGIS/Tiger tables from autogenerate
EXCLUDE_TABLES = {
    # PostGIS extension tables
    'spatial_ref_sys',
    'topology',
    # Tiger geocoder tables
    'addr', 'addrfeat', 'bg', 'county', 'county_lookup', 'countysub_lookup',
    'cousub', 'direction_lookup', 'edges', 'faces', 'featnames', 'geocode_settings',
    'geocode_settings_default', 'layer', 'loader_lookuptables', 'loader_platform',
    'loader_variables', 'pagc_gaz', 'pagc_lex', 'pagc_rules', 'place', 'place_lookup',
    'secondary_unit_lookup', 'state', 'state_lookup', 'street_type_lookup', 'tabblock',
    'tabblock20', 'tract', 'zcta5', 'zip_lookup', 'zip_lookup_all', 'zip_lookup_base',
    'zip_state', 'zip_state_loc',
}


def include_object(object, name, type_, reflected, compare_to):
    """Filter out PostGIS and Tiger geocoder tables from autogenerate."""
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


def get_url():
    """Get database URL from environment, converting async to sync if needed."""
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/pinpoint311")
    # Alembic needs sync driver, not asyncpg
    if "+asyncpg" in url:
        url = url.replace("+asyncpg", "")
    return url


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,  # Detect column type changes
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
