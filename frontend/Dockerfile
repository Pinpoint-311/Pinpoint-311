# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm ci

# Copy source and build. The `prebuild` script regenerates
# public/third-party-licenses.txt from the installed dependency tree, so the
# notices for everything compiled into the bundle ship with the bundle.
COPY . .
RUN npm run build

# Production stage - serve with nginx
FROM nginx:alpine

LABEL org.opencontainers.image.title="Pinpoint 311 Frontend" \
      org.opencontainers.image.description="Resident and staff web interface for the Pinpoint 311 municipal service-request platform" \
      org.opencontainers.image.source="https://github.com/Pinpoint-311/Pinpoint-311" \
      org.opencontainers.image.licenses="MIT"

# nginx:alpine is rebuilt upstream only every few weeks; Alpine's security
# fixes land in between (libexpat, libx11 at the time of writing). Upgrading
# here means a rebuild picks them up without waiting for the next base image.
RUN apk upgrade --no-cache

# Copy built assets from builder (includes third-party-licenses.txt, which
# nginx then serves at /third-party-licenses.txt)
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Release stamp: the same OCI label keys as the backend image, so the
# orchestrator and the host updater can check both halves of a release agree
# (see backend/Dockerfile). Last, so a new version reuses the cached layers.
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

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
