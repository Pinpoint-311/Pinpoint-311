"""Bring the database up to the image's schema, at startup, safely.

The problem this exists to fix
------------------------------
Until now the schema was created by `Base.metadata.create_all` in the app's
lifespan. That creates *missing tables* and nothing else -- it will not add a
column, widen a type, add an index or add a constraint to a table that already
exists. So a fresh install worked and an upgrade silently half-worked: the
container started, reported healthy, and 500ed the first time application code
touched a column the database did not have. Alembic was in the tree, with a
coherent revision chain, and was never invoked outside the demo compose file
(where it was written as `alembic upgrade head 2>/dev/null || true`, which
discards the error and the exit code both).

A town running this does not have a DBA. Nobody is going to notice schema drift
until a resident's report fails to submit. So the upgrade has to be automatic.

The policy
----------
Additive migrations apply automatically. Destructive ones stop the container and
print the command a human must run. "Destructive" is decided by reading what the
migration actually does, not by trusting a label -- see `classify_source`.

This split is the whole design. Hands-off updates are what make a small town
actually take security patches; auto-applying a column drop to a municipal
records database with no human in the loop is how a town loses records it is
legally required to keep. Additive/destructive is the line between those.

Before anything is applied, a pg_dump goes to the backup volume, and a dump that
fails aborts the migration. The nightly backup already exists but can be up to
24 hours stale and nothing verifies that it restores.

Concurrency
-----------
Everything runs under a Postgres advisory lock, so scaling the API to more than
one replica does not mean two containers running `alembic upgrade` at the same
moment. The second waits, then finds nothing pending.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("migrate")

# Any 64-bit constant works; it only has to be the same in every replica. Chosen
# once and never changed -- changing it would let an old and a new container
# migrate concurrently during a rolling deploy.
ADVISORY_LOCK_KEY = 8_311_311_001

# Set to "1" to apply destructive migrations without the confirmation gate. This
# is what the printed command sets, and it is deliberately not a nice name: it
# should look like something you only type on purpose.
ALLOW_DESTRUCTIVE_ENV = "PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION"

SKIP_ENV = "PINPOINT_SKIP_MIGRATIONS"

BACKUP_DIR_ENV = "PINPOINT_MIGRATION_BACKUP_DIR"
DEFAULT_BACKUP_DIR = "/backups"


# --------------------------------------------------------------------------
# classifying a migration -- pure, and the part worth testing hardest
# --------------------------------------------------------------------------

# Operations that can lose data, or whose effect cannot be known by reading it.
#
#   drop_table / drop_column   the obvious ones
#   alter_column with type_=   a type change rewrites every row and can truncate
#                              or fail partway
#   rename_table, and alter_column with new_column_name: no data is lost, but
#                              during a rolling deploy the old container is
#                              still querying the old name, so it breaks
#                              running code -- same blast radius, same gate
#   execute()                  arbitrary SQL. It may be a harmless backfill or
#                              it may be a DELETE. Unknowable means gated --
#                              except where the SQL is a literal string whose
#                              verb is provably additive, see _executes_are_safe.
#
# Deliberately NOT destructive:
#
#   create_table, add_column, create_index, create_unique_constraint --
#   additive. A unique constraint can fail on existing duplicates, but failing
#   is not the same as destroying, and the transaction rolls it back.
#   drop_index -- an index is derived data; dropping one cannot lose a row.
_DESTRUCTIVE_OPS = ("drop_table", "drop_column", "rename_table")

_OP_CALL = re.compile(r"\bop\.(\w+)\s*\(")
_ALTER_COLUMN = re.compile(r"\bop\.alter_column\s*\((.*?)\)\s*$", re.DOTALL | re.MULTILINE)

# SQL verbs that cannot lose data. Index creation is the case that actually
# comes up: a GIST index on a cast expression is not something Alembic's op
# layer can express, so it has to go through raw SQL, and gating every such
# migration would mean the index the road lookups depend on never gets created
# without a human. Reading the verb is still reading what the code does -- it is
# not a label the author can get wrong.
_SAFE_SQL = (
    "create index", "create unique index", "create table if not exists",
    "create extension", "comment on", "analyze", "set ", "reindex",
)

_STRING_LITERAL = re.compile(r"""(?:'{3}([\s\S]*?)'{3}|"{3}([\s\S]*?)"{3}|'([^'\n]*)'|"([^"\n]*)")""")

ADDITIVE = "additive"
DESTRUCTIVE = "destructive"


def _strip_comments_and_docstrings(source: str) -> str:
    """Remove `#` comments and triple-quoted blocks.

    Every Alembic revision has a docstring naming the operation ("drop the
    legacy media column"), and scanning raw text would classify an
    add-a-column migration as destructive because its docstring mentions a
    drop. The scan has to look at code.
    """
    source = re.sub(r'"""[\s\S]*?"""', "", source)
    source = re.sub(r"'''[\s\S]*?'''", "", source)
    return re.sub(r"#[^\n]*", "", source)


def upgrade_body(source: str) -> str:
    """Just the `def upgrade()` function.

    Every migration's `downgrade()` is full of drops by construction -- that is
    what a downgrade is. Scanning the whole file would mark every migration
    destructive and the gate would never let anything through.
    """
    cleaned = _strip_comments_and_docstrings(source)
    match = re.search(r"^def\s+upgrade\s*\([^)]*\)\s*(?:->[^:]+)?:\s*\n", cleaned, re.MULTILINE)
    if not match:
        return cleaned
    rest = cleaned[match.end():]
    # Stop at the next top-level `def`/`class` -- the body is everything indented.
    end = re.search(r"^(?:def|class)\s", rest, re.MULTILINE)
    return rest[:end.start()] if end else rest


def _executes_are_safe(body: str) -> bool:
    """True when every op.execute() in the body runs provably additive SQL.

    The argument has to be a plain string literal. A variable, an f-string with
    a substitution, or a call means the SQL is assembled at runtime and cannot
    be read here -- which is exactly the case that should stop and ask.

    Note the implicit-concatenation handling: the codebase wraps long DDL across
    lines as adjacent literals, so a single execute() call legitimately contains
    several strings. Only the first carries the verb; the rest are continuations
    and must not be judged on their own.
    """
    for call in re.finditer(r"\bop\.execute\s*\(", body):
        # Walk to the matching close paren so nested parens in the SQL survive.
        depth, i = 1, call.end()
        while i < len(body) and depth:
            depth += (body[i] == "(") - (body[i] == ")")
            i += 1
        args = body[call.end():i - 1].strip()

        pieces = [next(g for g in m.groups() if g is not None)
                  for m in _STRING_LITERAL.finditer(args)]
        if not pieces:
            return False  # not a literal — runtime-assembled SQL

        # Anything outside the literals (an f-prefix substitution, a `+ var`,
        # a `.format(`) means the final SQL is not what we just read.
        residue = _STRING_LITERAL.sub("", args)
        if re.search(r"[\w%+]", residue.replace(",", "")):
            return False

        statement = " ".join(pieces).strip().lower()
        if not statement.startswith(_SAFE_SQL):
            return False
    return True


def classify_source(source: str) -> str:
    """ADDITIVE or DESTRUCTIVE, decided by what `upgrade()` actually calls.

    Reading the code rather than trusting a declared flag is deliberate. A flag
    is a thing an author forgets to set, and the direction it fails in when
    forgotten is "auto-apply a column drop to a town's records". The scan cannot
    be forgotten.

    Unparseable input is DESTRUCTIVE. Every ambiguity in this function resolves
    toward "make a human look at it".
    """
    # No upgrade() at all means the file was unreadable, truncated, or is not a
    # migration. An empty `def upgrade(): pass` is a legitimate no-op revision
    # and is fine; a file we could not parse is not, and the difference is
    # whether the function is there.
    if not re.search(r"^def\s+upgrade\s*\(", _strip_comments_and_docstrings(source or ""),
                     re.MULTILINE):
        return DESTRUCTIVE

    body = upgrade_body(source or "")
    calls = set(_OP_CALL.findall(body))

    if calls & set(_DESTRUCTIVE_OPS):
        return DESTRUCTIVE

    if "execute" in calls and not _executes_are_safe(body):
        return DESTRUCTIVE

    # alter_column is additive when it only relaxes nullability or sets a
    # default, and destructive when it rewrites the type or renames.
    for args in _ALTER_COLUMN.findall(body):
        if "type_" in args or "new_column_name" in args:
            return DESTRUCTIVE

    # SQL executed through a raw connection rather than op.execute, which
    # bypasses the check above.
    #
    # Only *executing* counts. `op.get_bind()` on its own is how a migration
    # inspects the database to stay idempotent, and `sa.text("now()")` is the
    # ordinary way to write a server_default -- neither changes a row, and
    # flagging them marked six of the seven existing migrations destructive.
    if re.search(r"get_bind\s*\(\s*\)\s*\.\s*(?:execute|exec_driver_sql)\s*\(", body):
        return DESTRUCTIVE
    # Any receiver other than `op` -- `conn`, `connection`, `bind`, `session`,
    # whatever the author named the variable holding get_bind(). Matching only
    # `conn` let `bind = op.get_bind(); bind.execute(sa.delete(...))` walk
    # straight past the gate, and that exact shape shipped in a real revision.
    if re.search(r"\b(?!op\b)\w+\s*\.\s*(?:execute|exec_driver_sql)\s*\(", body):
        return DESTRUCTIVE

    return ADDITIVE


@dataclass
class Revision:
    revision: str
    path: Path
    kind: str = ADDITIVE

    @property
    def name(self) -> str:
        return self.path.stem


@dataclass
class Plan:
    """What the runner intends to do, before it does any of it."""

    pending: List[Revision] = field(default_factory=list)
    baseline: bool = False          # stamp an existing unmanaged database
    fresh: bool = False             # empty database, migrate from zero

    @property
    def destructive(self) -> List[Revision]:
        return [r for r in self.pending if r.kind == DESTRUCTIVE]

    @property
    def blocked(self) -> bool:
        """Whether a human has to look before anything is applied.

        A fresh database is never blocked, however destructive the chain looks.
        Replaying from base means the drop_column three revisions in is dropping
        a column from a table created two revisions earlier in the same run,
        with no rows in it -- nothing can be lost that did not exist a second
        ago. Gating that would mean every first-time install refuses to start
        because of something the project did to its own schema in February.

        The gate protects existing records. An empty database has none.
        """
        return bool(self.destructive) and not self.fresh

    @property
    def nothing_to_do(self) -> bool:
        return not self.pending and not self.baseline


def classify_revisions(pending: Sequence[str], sources: Dict[str, Tuple[Path, str]]) -> List[Revision]:
    """Attach a classification to each pending revision id.

    A revision whose file cannot be found is DESTRUCTIVE. That happens when the
    database is ahead of the image -- someone rolled a container back -- and
    guessing is exactly wrong there.
    """
    out: List[Revision] = []
    for rev in pending:
        if rev not in sources:
            out.append(Revision(rev, Path(f"<unknown:{rev}>"), DESTRUCTIVE))
            continue
        path, source = sources[rev]
        out.append(Revision(rev, path, classify_source(source)))
    return out


def format_plan(plan: Plan, allow_destructive: bool = False) -> List[str]:
    """The lines printed to the container log.

    This log is the only thing a town's IT contact will ever see of this system,
    and they will be reading it while something is broken. Every line says what
    happened to which revision.
    """
    lines: List[str] = []
    if plan.fresh:
        # Returns here: a fresh database has no pending list to report, and
        # falling through printed "creating schema from scratch" immediately
        # followed by "schema is up to date".
        return ["[migrate] empty database — creating the schema from the models"]
    if plan.baseline:
        # Also returns: "pending: 0 revision(s)" underneath this reads as though
        # something was checked and skipped, rather than adopted.
        return ["[migrate] existing database has no migration history — recording the current "
                "state as the baseline (no schema changes applied)"]
    if plan.nothing_to_do:
        lines.append("[migrate] schema is up to date")
        return lines

    lines.append(f"[migrate] pending: {len(plan.pending)} revision(s)")
    for rev in plan.pending:
        # On a fresh database the classification is noise -- there is nothing to
        # destroy -- and printing DESTRUCTIVE next to a revision that is about
        # to be applied anyway reads as a warning that was ignored.
        label = "" if plan.fresh else f"  {rev.kind.upper()}"
        lines.append(f"[migrate]   {rev.revision}  {rev.name}{label}")
    if plan.blocked and allow_destructive:
        # The operator followed the instructions in the previous run's log. Say
        # so explicitly -- printing REFUSING TO START and then migrating anyway
        # is the log telling the reader the opposite of what happened.
        lines.append(f"[migrate] {ALLOW_DESTRUCTIVE_ENV} is set — applying the destructive "
                     "revision(s) above.")
    elif plan.blocked:
        lines.append("[migrate] REFUSING TO START — a destructive migration needs a human.")
        lines.append("[migrate] It may drop a column or table, rewrite a type, or run raw SQL.")
        lines.append("[migrate] Review the revision(s) above, confirm you have a restorable "
                     "backup, then run:")
        lines.append("[migrate]   docker compose run --rm \\")
        lines.append(f"[migrate]     -e {ALLOW_DESTRUCTIVE_ENV}=1 backend alembic upgrade head")
    return lines


# --------------------------------------------------------------------------
# talking to the database
# --------------------------------------------------------------------------

def sync_url(url: Optional[str] = None) -> str:
    """A psycopg2 URL. Alembic is synchronous; the app's URL is asyncpg."""
    raw = url or os.environ.get("DATABASE_URL", "")
    return raw.replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


def _alembic_config(script_location: Optional[str] = None):
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", script_location or str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url())
    return cfg


def revision_sources(script_location: Optional[str] = None) -> Dict[str, Tuple[Path, str]]:
    """{revision id: (path, source)} for every migration file in the image."""
    root = Path(__file__).resolve().parents[2]
    versions = Path(script_location or (root / "alembic")) / "versions"
    out: Dict[str, Tuple[Path, str]] = {}
    if not versions.is_dir():
        return out
    for path in sorted(versions.glob("*.py")):
        try:
            source = path.read_text()
        except Exception:
            continue
        match = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", source, re.MULTILINE)
        if match:
            out[match.group(1)] = (path, source)
    return out


def build_plan(current: Optional[str], has_tables: bool,
               script_location: Optional[str] = None) -> Plan:
    """Work out what needs doing, without doing any of it.

    Three states a database can be in:

      * empty                    -> migrate from zero
      * populated, no history    -> the create_all installs that predate this
                                    module. Their schema already matches the
                                    models, so the honest move is to record the
                                    current head as the baseline and migrate
                                    forward from there. Replaying migrations
                                    against those tables would fail on the first
                                    create_table.
      * populated, has history   -> normal upgrade
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config(script_location)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    sources = revision_sources(script_location)

    if current is None and has_tables:
        return Plan(pending=[], baseline=True)

    if current is None:
        # Built from the models, not by replaying the chain.
        #
        # The chain cannot build a database from scratch and never could: its
        # base revision ALTERs `departments`, and no revision creates that
        # table. Nothing noticed because the schema was always produced by
        # create_all and the migrations only ever ran as incremental patches on
        # top of it. Replaying from base fails on the first revision.
        #
        # Writing a from-nothing initial revision for forty-odd tables would be
        # a second description of the schema to keep in sync with the models,
        # which is the problem, not the fix. The models are authoritative for a
        # new install; the chain is for moving an existing one forward.
        return Plan(pending=[], fresh=True)

    if current == head:
        return Plan(pending=[])

    pending = []
    for rev in script.walk_revisions(base=current, head=head or "heads"):
        if rev.revision != current:
            pending.append(rev.revision)
    return Plan(pending=classify_revisions(list(reversed(pending)), sources))


# How many pre-migration dumps to keep. These are unencrypted plaintext copies
# of a municipality's entire database -- resident names, addresses, phone
# numbers, emails and photos -- so they are kept on a local volume rather than
# shipped anywhere, and old ones are pruned. Three is enough to roll back
# through a bad release without accumulating years of PII on disk.
KEEP_BACKUPS = 3


def _prune(directory: Path) -> None:
    """Delete all but the newest KEEP_BACKUPS dumps.

    Unbounded growth here is not just a disk problem: every retained dump is a
    full copy of the resident database sitting outside the retention policy that
    governs the live tables, which is the kind of thing a records review finds.
    """
    try:
        dumps = sorted(directory.glob("pre-migrate-*.sql.gz"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in dumps[KEEP_BACKUPS:]:
            stale.unlink()
            logger.info("[migrate] pruned old dump %s", stale.name)
    except Exception as exc:
        logger.warning("[migrate] could not prune old dumps: %s", exc)


def _backup(engine_url: str) -> Optional[Path]:
    """pg_dump to the backup volume. None means the dump failed.

    A failed dump aborts the migration -- the point of taking it is that the
    migration is the risky step, so proceeding without one gives up the only
    thing making an auto-applied schema change acceptable.

    Deliberately local and deliberately not the nightly S3 backup: this has to
    complete before the migration runs, in the startup path, and an S3 round
    trip for a multi-GB database would make every container restart glacial.
    """
    directory = Path(os.environ.get(BACKUP_DIR_ENV, DEFAULT_BACKUP_DIR))
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error("[migrate] cannot create backup directory %s: %s", directory, exc)
        return None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"pre-migrate-{stamp}.sql.gz"
    try:
        with open(target, "wb") as handle:
            dump = subprocess.Popen(["pg_dump", "--no-owner", "--no-acl", engine_url],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            gzip_proc = subprocess.Popen(["gzip", "-c"], stdin=dump.stdout, stdout=handle,
                                         stderr=subprocess.PIPE)
            dump.stdout.close()
            gzip_proc.communicate()
            _, err = dump.communicate()
            if dump.returncode != 0 or gzip_proc.returncode != 0:
                logger.error("[migrate] pg_dump failed: %s", (err or b"").decode()[:500])
                return None
    except FileNotFoundError:
        logger.error("[migrate] pg_dump is not installed in this image")
        return None
    except Exception as exc:
        logger.error("[migrate] backup failed: %s", exc)
        return None

    size = target.stat().st_size
    if size < 1024:
        # pg_dump can exit 0 having written almost nothing if the connection
        # drops mid-stream. A dump too small to be a real database is not a
        # backup, and treating it as one is worse than having none.
        logger.error("[migrate] dump is implausibly small (%d bytes); treating as failed", size)
        return None
    logger.info("[migrate] pre-migration dump → %s (%.1f MB)", target, size / 1_048_576)
    _prune(directory)
    return target


def run(script_location: Optional[str] = None) -> int:
    """Migrate, or refuse to. Returns a process exit code.

    0 means the schema matches the image and the API may start. Anything else
    means it must not -- serving traffic against a schema you could not
    reconcile is how a half-migrated database gets written to.
    """
    if os.environ.get(SKIP_ENV, "").lower() in ("1", "true", "yes"):
        logger.warning("[migrate] skipped by %s — the schema is not being checked", SKIP_ENV)
        return 0

    url = sync_url()
    if not url:
        logger.error("[migrate] DATABASE_URL is not set")
        return 1

    from alembic import command
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(url, poolclass=None)

    try:
        with engine.connect() as conn:
            # Held for the whole operation. A second replica blocks here rather
            # than racing, and finds nothing pending once it acquires.
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
            try:
                inspector = inspect(conn)
                tables = set(inspector.get_table_names())
                has_history = "alembic_version" in tables
                # Ignore alembic's own bookkeeping table when asking "is this
                # database empty?", or a stamped-but-empty DB looks populated.
                has_tables = bool(tables - {"alembic_version", "spatial_ref_sys"})

                current = None
                if has_history:
                    row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
                    current = row[0] if row else None

                allow_destructive = os.environ.get(ALLOW_DESTRUCTIVE_ENV, "") == "1"
                plan = build_plan(current, has_tables, script_location)
                for line in format_plan(plan, allow_destructive):
                    logger.info(line)

                if plan.blocked and not allow_destructive:
                    return 2

                if plan.fresh:
                    # Create from the models, then record head so the next
                    # release migrates forward normally. The indexes and
                    # triggers that Alembic cannot express are applied by
                    # _run_schema_migrations when the app starts, as they
                    # always have been.
                    from app.db.session import Base
                    import app.models  # noqa: F401 - registers every table

                    Base.metadata.create_all(engine)
                    command.stamp(_alembic_config(script_location), "head")
                    logger.info("[migrate] created %d tables from the models and recorded head",
                                len(Base.metadata.tables))
                    return 0

                if plan.baseline:
                    command.stamp(_alembic_config(script_location), "head")
                    logger.info("[migrate] baseline recorded")
                    return 0

                if plan.nothing_to_do:
                    return 0

                # No point dumping an empty database.
                if has_tables and not _backup(url):
                    logger.error("[migrate] refusing to migrate without a backup")
                    return 3

                command.upgrade(_alembic_config(script_location), "head")
                logger.info("[migrate] applied %d revision(s), now at head", len(plan.pending))
                return 0
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
    except Exception as exc:
        logger.exception("[migrate] failed: %s", exc)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    import sys

    # Root at WARNING, ours at INFO: Alembic logs its autogenerate plugin
    # registration at INFO, and a dozen "setup plugin" lines above the actual
    # migration report is exactly the noise that makes an operator stop reading
    # container logs.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger.setLevel(logging.INFO)
    sys.exit(run())
