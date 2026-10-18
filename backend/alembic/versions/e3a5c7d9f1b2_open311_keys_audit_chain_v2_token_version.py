"""Open311 API keys, audit chain v2, session revocation, polygon context layers, and secure upgrades.

Revision ID: e3a5c7d9f1b2
Revises: d2e4f6a8b0c1
Create Date: 2026-10-18

One revision for five changes that ship together. The orchestrator accepts a
town only at exactly {min_db_revision, db_revision}; three chained revisions in
one release would leave every town on d2e4f6a8b0c1 outside that window.

Open311 (app/services/open311_keys.py):
  open311_api_keys   keys third-party Open311 clients present on POST
                     requests.json. Only a SHA-256 hash and an 8-character
                     prefix are stored.
  open311_settings   singleton: "allow anonymous Open311 submissions" and an
                     optional jurisdiction_id. No row is inserted; an absent row
                     reads as the defaults (anonymous OFF, any jurisdiction).

Audit chain v2 (app/core/audit_chain.py):
  audit_logs.chain_version NOT NULL default 1 -- every existing row is a v1
     entry whose hash covered a timestamp that was never stored, so it can never
     be recomputed. New rows are v2. Verification reports v1 rows as an
     unverifiable legacy segment and starts at the first v2 row, which links to
     the last legacy row's stored hash.
  audit_logs.context_salt / context_digest (nullable): the commitment to
     ip_address/user_agent, which retention deletes after 90 days.
  audit_anchors.auth_head_id / auth_head_hash / auth_entry_count /
     auth_legacy_count (nullable): the nightly anchor records the audit_logs
     head too, so cutting entries off the tail is detectable.

Session revocation (app/core/auth.py):
  users.token_version NOT NULL default 0. Session tokens carry `tv`; a token
     whose version no longer matches the row is refused. Tokens issued before
     this revision have no `tv`, read as 0, so the deploy signs nobody out.

Polygon context layers (app/services/gis_layers.py):
  map_layer_features  one row per polygon of a table-backed layer (tax
                      parcels, zones): layer_id FK ON DELETE CASCADE,
                      feature_key, properties JSONB, geom geometry(Geometry,
                      4326) with a GIST index, and (layer_id, feature_key).
  map_layers.feature_storage NOT NULL default 'inline' -- every existing layer
     keeps its features in map_layers.geojson, exactly as before.
  map_layers.feature_id_property / label_property / staff_properties /
     available_properties / feature_count / features_imported_at (nullable).
  service_requests.gis_context JSONB (nullable) with a GIN jsonb_path_ops
     index: the containing features snapshotted at intake.

Secure upgrades, Phase 3 (app/services/upgrades.py, docs/design/secure-upgrades.md):
  upgrade_requests       upgrade / rollback / restart requests admins file in
                         the console; status, approval, claim and outcome.
  upgrade_request_steps  each step the host updater reported for a request.
  updater_tokens         the updater's bearer token: SHA-256 hash and an
                         8-character prefix only.
  updater_releases       the release list the updater last reported.
  updater_settings       singleton: require_two_person_approval (server
                         default true) and updater_last_seen_at. No row is
                         inserted; an absent row reads as the defaults.

Additive only (expand): new tables, nullable columns, NOT NULL columns with
server defaults, and no data writes. Older code ignores all of it, so the
schema floor stays at d2e4f6a8b0c1.
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "e3a5c7d9f1b2"
down_revision = "d2e4f6a8b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Open311
    op.create_table(
        "open311_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("contact_email", sa.String(254), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(100), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_open311_api_keys_key_hash"),
    )
    op.create_index("ix_open311_api_keys_key_prefix", "open311_api_keys", ["key_prefix"])
    op.create_table(
        "open311_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("allow_anonymous_submissions", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("jurisdiction_id", sa.String(100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_by", sa.String(100), nullable=True),
    )

    # Audit chain v2
    op.add_column("audit_logs", sa.Column("chain_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("audit_logs", sa.Column("context_salt", sa.String(length=32), nullable=True))
    op.add_column("audit_logs", sa.Column("context_digest", sa.String(length=64), nullable=True))
    op.add_column("audit_anchors", sa.Column("auth_head_id", sa.Integer(), nullable=True))
    op.add_column("audit_anchors", sa.Column("auth_head_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_anchors", sa.Column("auth_entry_count", sa.Integer(), nullable=True))
    op.add_column("audit_anchors", sa.Column("auth_legacy_count", sa.Integer(), nullable=True))

    # Session revocation
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    # Polygon context layers
    op.add_column("map_layers", sa.Column("feature_storage", sa.String(length=10), nullable=False, server_default="inline"))
    op.add_column("map_layers", sa.Column("feature_id_property", sa.String(length=100), nullable=True))
    op.add_column("map_layers", sa.Column("label_property", sa.String(length=100), nullable=True))
    op.add_column("map_layers", sa.Column("staff_properties", sa.JSON(), nullable=True))
    op.add_column("map_layers", sa.Column("available_properties", sa.JSON(), nullable=True))
    op.add_column("map_layers", sa.Column("feature_count", sa.Integer(), nullable=True))
    op.add_column("map_layers", sa.Column("features_imported_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "map_layer_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("layer_id", sa.Integer(), sa.ForeignKey("map_layers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_key", sa.String(length=200), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=True),
        # spatial_index=False: the GIST index is created by name just below
        # rather than implicitly by geoalchemy2, so downgrade and the model agree.
        sa.Column("geom", Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=False),
    )
    op.create_index("ix_map_layer_features_layer_key", "map_layer_features", ["layer_id", "feature_key"])
    op.create_index("ix_map_layer_features_geom", "map_layer_features", ["geom"], postgresql_using="gist")
    op.add_column("service_requests", sa.Column("gis_context", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_service_requests_gis_context", "service_requests", ["gis_context"],
        postgresql_using="gin", postgresql_ops={"gis_context": "jsonb_path_ops"},
    )

    # Secure upgrades (Phase 3)
    op.create_table(
        "upgrade_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("target_tag", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("approved_by", sa.String(length=100), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.String(length=100), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_report_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("outcome_summary", sa.Text(), nullable=True),
        sa.Column("allow_destructive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_upgrade_requests_status", "upgrade_requests", ["status"])
    op.create_table(
        "upgrade_request_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("upgrade_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_upgrade_request_steps_request_id", "upgrade_request_steps", ["request_id"])
    op.create_table(
        "updater_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(length=100), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_updater_tokens_token_hash"),
    )
    op.create_index("ix_updater_tokens_token_prefix", "updater_tokens", ["token_prefix"])
    op.create_table(
        "updater_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tag", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("prerelease", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signature_verified", sa.Boolean(), nullable=True),
        sa.Column("gate_passed", sa.Boolean(), nullable=True),
        sa.Column("attested", sa.Boolean(), nullable=True),
        sa.Column("db_revision", sa.String(length=64), nullable=True),
        sa.Column("min_db_revision", sa.String(length=64), nullable=True),
        sa.Column("compatible_with_this_instance", sa.Boolean(), nullable=True),
        sa.Column("compatibility_detail", sa.Text(), nullable=True),
        sa.Column("backend_digest", sa.String(length=80), nullable=True),
        sa.Column("frontend_digest", sa.String(length=80), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("tag", name="uq_updater_releases_tag"),
    )
    op.create_table(
        "updater_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("require_two_person_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updater_last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updater_version", sa.String(length=32), nullable=True),
        sa.Column("current_report", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("updater_settings")
    op.drop_table("updater_releases")
    op.drop_index("ix_updater_tokens_token_prefix", table_name="updater_tokens")
    op.drop_table("updater_tokens")
    op.drop_index("ix_upgrade_request_steps_request_id", table_name="upgrade_request_steps")
    op.drop_table("upgrade_request_steps")
    op.drop_index("ix_upgrade_requests_status", table_name="upgrade_requests")
    op.drop_table("upgrade_requests")
    op.drop_index("ix_service_requests_gis_context", table_name="service_requests")
    op.drop_column("service_requests", "gis_context")
    op.drop_index("ix_map_layer_features_geom", table_name="map_layer_features")
    op.drop_index("ix_map_layer_features_layer_key", table_name="map_layer_features")
    op.drop_table("map_layer_features")
    op.drop_column("map_layers", "features_imported_at")
    op.drop_column("map_layers", "feature_count")
    op.drop_column("map_layers", "available_properties")
    op.drop_column("map_layers", "staff_properties")
    op.drop_column("map_layers", "label_property")
    op.drop_column("map_layers", "feature_id_property")
    op.drop_column("map_layers", "feature_storage")
    op.drop_column("users", "token_version")
    op.drop_column("audit_anchors", "auth_legacy_count")
    op.drop_column("audit_anchors", "auth_entry_count")
    op.drop_column("audit_anchors", "auth_head_hash")
    op.drop_column("audit_anchors", "auth_head_id")
    op.drop_column("audit_logs", "context_digest")
    op.drop_column("audit_logs", "context_salt")
    op.drop_column("audit_logs", "chain_version")
    op.drop_table("open311_settings")
    op.drop_index("ix_open311_api_keys_key_prefix", table_name="open311_api_keys")
    op.drop_table("open311_api_keys")
