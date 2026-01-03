# Use Debian slim as the base
FROM debian:bookworm-slim AS base
WORKDIR /app

# Install system dependencies needed for Django/GeoDjango
RUN apt-get -y update && apt-get install -y --no-install-recommends \
    git \
    binutils \
    libproj-dev \
    libgdal-dev \
    gdal-bin \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install Bun from official image
COPY --from=oven/bun:1.3.5 /usr/local/bin/bun /usr/local/bin/bun

# Build stage - install dependencies and build static files
FROM base AS build
WORKDIR /app

# Install build dependencies
RUN apt-get -y update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    file \
    && rm -rf /var/lib/apt/lists/*

# Install Bun dependencies (including devDependencies for vite build)
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Copy Python version file so uv knows which Python to install
COPY .python-version ./

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
WORKDIR /app

# Install only essential runtime dependencies
RUN apt-get -y update && apt-get install -y --no-install-recommends \
    libgdal32 \
    libproj25 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.13 /usr/bin/python3

# Copy uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy Python (managed by uv) and virtual environment from build stage
COPY --from=build /root/.local/share/uv/python /root/.local/share/uv/python
COPY --from=build /app/.venv /app/.venv

# Copy only runtime-necessary files from build stage
COPY --from=build /app/manage.py /app/
COPY --from=build /app/pyproject.toml /app/
COPY --from=build /app/uv.lock /app/
COPY --from=build /app/.python-version /app/
COPY --from=build /app/images /app/images
COPY --from=build /app/osm_auth /app/osm_auth
COPY --from=build /app/scripts /app/scripts
COPY --from=build /app/templates /app/templates
COPY --from=build /app/yesterdays /app/yesterdays
COPY --from=build /app/static /app/static

# Run the application
CMD [ \
    "sh", "-c", \
    "uv run uvicorn yesterdays.asgi:application --host 0.0.0.0 --port 8000" \
    ]
