# Build stage - install dependencies and build static files
FROM debian:bookworm-slim AS build
WORKDIR /app

# Install system and build dependencies
RUN apt-get -y update && apt-get install -y --no-install-recommends \
    git \
    binutils \
    libproj-dev \
    libgdal-dev \
    gdal-bin \
    curl \
    ca-certificates \
    gcc \
    g++ \
    make \
    file \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Bun from official image
COPY --from=oven/bun:1.3.5 /usr/local/bin/bun /usr/local/bin/bun

# Install Bun dependencies (including devDependencies for vite build)
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Copy Python version file so uv knows which Python to install
COPY .python-version ./

# Install Python to a path that will also work in the release image
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python

# Install Python dependencies (uv will download and manage Python)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock,relabel=shared \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml,relabel=shared \
    uv sync --locked --no-install-project

# Copy project files - only what's needed for the application
COPY uv.lock ./
COPY manage.py ./
COPY vite.config.js ./
COPY pyproject.toml ./
COPY assets ./assets
COPY images ./images
COPY maps ./maps
COPY subjects ./subjects
COPY activity ./activity
COPY osm_auth ./osm_auth
COPY scripts ./scripts
COPY templates ./templates
COPY yesterdays ./yesterdays

# Install project itself
RUN uv sync --locked

# Build static files in correct order:
# 1. Create static directory first
RUN mkdir -p /app/static

# 2. Run bun build to generate Vite-bundled JS/CSS into /static
RUN bun run build

# Final runtime image - minimal Debian
FROM debian:bookworm-slim AS release

# Create non-root user
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home app

WORKDIR /app

# Install only essential runtime dependencies
RUN apt-get -y update && apt-get install -y --no-install-recommends \
    libgdal32 \
    libproj25 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Python (managed by uv) and virtual environment from build stage
COPY --from=build /opt/uv/python /opt/uv/python
COPY --from=build --chown=app:app /app/.venv /app/.venv

# Copy only runtime-necessary files from build stage
COPY --from=build --chown=app:app /app/manage.py /app/
COPY --from=build --chown=app:app /app/pyproject.toml /app/
COPY --from=build --chown=app:app /app/uv.lock /app/
COPY --from=build --chown=app:app /app/.python-version /app/
COPY --from=build --chown=app:app /app/images /app/images
COPY --from=build --chown=app:app /app/maps /app/maps
COPY --from=build --chown=app:app /app/subjects /app/subjects
COPY --from=build --chown=app:app /app/activity /app/activity
COPY --from=build --chown=app:app /app/osm_auth /app/osm_auth
COPY --from=build --chown=app:app /app/scripts /app/scripts
COPY --from=build --chown=app:app /app/templates /app/templates
COPY --from=build --chown=app:app /app/yesterdays /app/yesterdays
COPY --from=build --chown=app:app /app/static /app/static

USER app

# Run the application
CMD ["/app/.venv/bin/uvicorn", "yesterdays.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
