# Development Environment

There are two ways to run Yesterdays locally:

- **[Quick start with Docker Compose](#quick-start-docker-compose)** (recommended) — write one environment file and bring the whole stack up with a single command.
- **[Manual setup](#manual-setup)** — run each service yourself on the host. More moving parts, but useful if you can't use containers or want fine-grained control over individual services.

## Quick start (Docker Compose)

!!! tip "This is the recommended path for most contributors."
    `docker compose` builds a single image containing the Django app, the Celery workers, and Vite, then runs them alongside PostgreSQL, RabbitMQ, and Oxigraph. Your source tree is bind-mounted into the containers, so code edits reload live.

You only need [Docker](https://docs.docker.com/get-docker/) with the Compose plugin.

### 1. Create the database volume

The database lives in a named volume that is intentionally **external** to Compose, so it survives `docker compose down -v` and can't be destroyed by accident. Create it once:

```sh
docker volume create georef-postgres-data
```

### 2. Write your environment file { #env-file }

Save the following to `my.env` in the root of the repository, filling in the secret values:

```sh title="my.env"
# Cloudflare R2 Key
export IMPORT_R2_ENDPOINT_URL='https://<ENDPOINT-ID>.r2.cloudflarestorage.com'
export IMPORT_R2_ACCESS_KEY_ID=<ACCESS-KEY-ID>
export IMPORT_R2_SECRET_ACCESS_KEY=<SECRET-ACCESS-KEY>
export IMPORT_R2_REGION=enam
export IMPORT_R2_BUCKET_NAME=cdn
export IMPORT_R2_PUBLIC_URL_BASE='https://cdn.maprva.org'

# Protomaps Key
export PROTOMAPS_API_KEY=6f7a752e00e84ef9

# PostgreSQL Connection
export PG_DBNAME=georef
export PG_USER=django_user
export PG_PASSWORD=dev_password
export PG_HOST=localhost
export PG_PORT=5432
export PG_SSL_MODE=disable

# RabbitMQ Connection
export CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//

# Local Development Settings
export LOCAL_DEV=0
export ALLOW_HARDCODED_ADMIN=1
export DJANGO_DEBUG=1
export DJANGO_VITE_DEV_MODE=True
```

!!! note
    Compose reads this file directly (via `env_file`) and overrides the host-specific values — `PG_HOST`, `CELERY_BROKER_URL`, and `OXIGRAPH_URL` — to point at the other containers. The same `my.env` therefore works unchanged for the [manual setup](#manual-setup) below, where the `localhost` values apply instead.

### 3. Start the stack

```sh
docker compose up --build
```

This builds the image (on the first run) and starts PostgreSQL, RabbitMQ, Oxigraph, the Django dev server, two Celery workers, the Beat scheduler, and Vite. Database migrations run automatically as the web service comes up.

Once the logs settle, the site is live:

| What                | URL                           | Credentials       |
| ------------------- | ----------------------------- | ----------------- |
| Yesterdays          | <http://localhost:8000>       | –                 |
| Django admin        | <http://localhost:8000/admin> | `admin` / `admin` |
| RabbitMQ management | <http://localhost:15672>      | `guest` / `guest` |

### Subsequent runs

- Moving forward, plain `docker compose up` is enough, without `--build`.
- After changing dependencies (`pyproject.toml` / `uv.lock`, or `package.json`), rebuild the image with `docker compose build`. The virtualenv is baked into the image (but no need to clear the volume!)
- Stop everything with `docker compose down`. The database will persist unless you specifically delete the volume.

## Manual setup

Here's what you need to run Yesterdays manually:

- [`uv`](https://docs.astral.sh/uv/),
- [`bun`](https://bun.com/),
- a PostgreSQL instance with the pgvector and PostGIS extensions,
- a RabbitMQ instance for running background tasks (optional),
- an Oxigraph instance for caching and querying Wikidata relationships (optional).

### Set up environment variables

If you haven't already, create `my.env` as shown above in [Write your environment file](#env-file). Then load it into your shell:

```sh
source my.env
```

The `localhost` values for `PG_HOST` and `CELERY_BROKER_URL` apply when running each service directly on the host.

### Run Database

The recommended way to run your database is using the [MapRVA/cnpg-postgis-pgvector](https://github.com/MapRVA/cnpg-postgis-pgvector) container.

=== "podman"

    ```
    podman run -d --replace --name georef-postgres \
        -e POSTGRES_DB=georef \
        -e POSTGRES_USER=django_user \
        -e POSTGRES_PASSWORD=dev_password \
        -p 5432:5432 \
        ghcr.io/maprva/postgis-pgvector-local:latest
    ```

=== "docker"

    ```
    docker run -d --name georef-postgres \
        -e POSTGRES_DB=georef \
        -e POSTGRES_USER=django_user \
        -e POSTGRES_PASSWORD=dev_password \
        -p 5432:5432 \
        ghcr.io/maprva/postgis-pgvector-local:latest
    ```

If you'd like, you can use a volume to persist the database between container restarts:

=== "podman"

    ```
    podman run -d --replace --name georef-postgres \
            -e POSTGRES_DB=georef \
            -e POSTGRES_USER=django_user \
            -e POSTGRES_PASSWORD=dev_password \
            -p 5432:5432 \
            -v georef-postgres-data:/var/lib/postgresql/data \
            ghcr.io/maprva/postgis-pgvector-local:latest
    ```

=== "docker"

    ```
    docker run -d --name georef-postgres \
        -e POSTGRES_DB=georef \
        -e POSTGRES_USER=django_user \
        -e POSTGRES_PASSWORD=dev_password \
        -p 5432:5432 \
        -v georef-postgres-data:/var/lib/postgresql/data \
        ghcr.io/maprva/postgis-pgvector-local:latest
    ```

### (Optional) Run Task Queue

Yesterdays uses Celery with RabbitMQ to manage background processing tasks.

=== "podman"

    ```
    podman run -d --replace --name rabbitmq \
        -p 5672:5672 \
        -p 15672:15672 \
        docker.io/library/rabbitmq:3-management
    ```

=== "docker"

    ```
    docker run -d --name rabbitmq \
        -p 5672:5672 \
        -p 15672:15672 \
        rabbitmq:3-management
    ```

To run background tasks, you'll also need to start a Celery worker and (optionally) the beat scheduler for periodic tasks:

```sh
# Run an background worker in one terminal
uv run celery -A yesterdays worker --loglevel=info -Q background

# Run an urgent worker in another terminal (for searches)
uv run celery -A yesterdays worker --loglevel=info -Q urgent

# Run the beat scheduler (for queuing periodic tasks) in another terminal
uv run celery -A yesterdays beat --loglevel=info
```

### (Optional) Run Graph Database

Yesterdays uses a graph database, Oxigraph, to cache and query Wikidata relationships for our [subjects](/usage/subjects/). This example uses a volume to persist the database between restarts, similar to the PostgreSQL example above:

=== "podman"

    ```
    podman run -d \
        --name oxigraph \
        -p 127.0.0.1:7878:7878 \
        -v oxigraph-data:/data \
        --restart=unless-stopped \
        ghcr.io/oxigraph/oxigraph:0.5.8 \
        serve --location /data --bind 0.0.0.0:7878 --union-default-graph
    ```

=== "docker"

    ```
    docker run -d \
        --name oxigraph \
        -p 127.0.0.1:7878:7878 \
        -v oxigraph-data:/data \
        --restart=unless-stopped \
        ghcr.io/oxigraph/oxigraph:0.5.8 \
        serve --location /data --bind 0.0.0.0:7878 --union-default-graph
    ```

### Install dependencies

```
uv sync
```

### Apply database migrations

```
uv run manage.py migrate
```

### Run Vite

Vite bundles JavaScript and CSS assets for Yesterdays.
It is important to run Vite in the background during development:

```
bun install
bun run dev
```

### Run the dev server!

In a separate terminal (keep Vite running):

```
uv run manage.py runserver
```

The site should now be live at <http://localhost:8000>.
