# syntax=docker/dockerfile:1

# deploy/templates lives at the repository root, outside this build context.
# Release builds pass it in as a named context
# (`--build-context deploy-templates=deploy/templates`, see
# scripts/build-release.sh and the CI workflows), which replaces this empty
# stage; a plain `docker build ./backend` still works and simply ships none,
# in which case /api/deploy-templates falls back to the published copy.
FROM scratch AS deploy-templates

FROM python:3.11-slim

LABEL org.opencontainers.image.title="Pinpoint 311 Backend" \
      org.opencontainers.image.description="API, task workers and Open311 endpoints for the Pinpoint 311 municipal service-request platform" \
      org.opencontainers.image.source="https://github.com/Pinpoint-311/Pinpoint-311" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# tesseract-ocr backs the free, offline licence-plate detector (Apache 2.0).
# libGL/libglib are what opencv-python-headless still links against.
#
# No git and no Docker CLI. This image is what production runs, and it runs
# without a source checkout or the host's Docker socket (docs/RELEASES.md):
# the version comes from the build stamp below, and upgrades and restarts are
# the host updater's job. The binaries would only invite putting the socket
# back. app/services/self_management.py reads their absence as "the secure
# setup" and the console says so.
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    gcc \
    libpq-dev \
    postgresql-client \
    # gnupg: backups are encrypted and decrypted with gpg (backup_service.py).
    # It was dropped with the Docker CLI's apt-key setup in 1.9.0-rc1 and every
    # scheduled backup failed at "Encrypting backup" -- tests/test_image_tools.py.
    gnupg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-onnx.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir --no-deps -r requirements-onnx.txt

COPY . .

# Emit the license notices for everything installed above. This image is
# redistributed as a binary artifact, so the notices have to travel inside it --
# including the LGPL text and source pointer for psycopg2-binary.
RUN python scripts/generate_licenses.py /app/THIRD-PARTY-LICENSES.txt

COPY --from=deploy-templates / /app/deploy/templates/

# Release stamp. CI (.github/workflows/build-publish.yml, .gitlab-ci.yml) and
# scripts/build-release.sh pass these; the same keys the orchestrator and the
# host updater read with `_stamp_from_labels`. Declared last so a new version
# does not invalidate the dependency layers above.
#
# They are also exported as environment variables, which is where the app
# reads its version from (app/core/config.py -> /api/health/quick). The label
# says what the signed artifact is; the env makes the running code say the
# same thing without a checkout to ask.
ARG PINPOINT_VERSION=""
ARG GIT_SHA=""
ARG DB_REVISION=""
ARG MIN_DB_REVISION=""
LABEL org.opencontainers.image.version="${PINPOINT_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.pinpoint311.app.version="${PINPOINT_VERSION}" \
      org.pinpoint311.app.git_sha="${GIT_SHA}" \
      org.pinpoint311.app.db_revision="${DB_REVISION}" \
      org.pinpoint311.app.min_db_revision="${MIN_DB_REVISION}"
ENV PINPOINT_VERSION="${PINPOINT_VERSION}" \
    GIT_SHA="${GIT_SHA}" \
    DB_REVISION="${DB_REVISION}" \
    MIN_DB_REVISION="${MIN_DB_REVISION}"

EXPOSE 8000

# The entrypoint reconciles the database schema before the API serves anything.
# It refuses to start on a schema it could not bring to head -- see
# app/db/migrate.py for why that is better than starting and 500ing later.
RUN chmod +x /app/scripts/entrypoint.sh
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
