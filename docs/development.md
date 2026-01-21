# Developing Yesterdays

First of all, thank you for your interest in contributing to Yesterdays!

If you would like to contribute to the development of Yesterdays, but aren't quite ready to dive into coding, please feel free to [file feature requests and bug reports here](https://github.com/MapRVA/yesterdays/issues/new/choose).
Your feedback is greatly appreciated!

## Contribution Guidelines

In general, we welcome any pull requests to our GitHub repository.
If you'd like to make a big change, please engage with us in a GitHub Issue or via Slack first so that we can coordinate our efforts.

## Setting Up Your Development Environment

To run Yesterdays locally, you need:

- [`uv`](https://docs.astral.sh/uv/),
- [`bun`](https://bun.com/),
- a PostgreSQL instance with the pgvector and PostGIS extensions,
- a RabbitMQ instance for running background tasks (optional).

Please follow the instructions below to set these up in your development environment.

### Run Database

The recommended way to run your database is using podman and
[MapRVA/cnpg-postgis-pgvector](https://github.com/MapRVA/cnpg-postgis-pgvector).

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
        rabbitmq:3-management
    ```

=== "docker"

    ```
    docker run -d --name rabbitmq \
        -p 5672:5672 \
        -p 15672:15672 \
        rabbitmq:3-management
    ```

### Set up environment variables

Setup the following environment variables:

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

Save those to `my.env` in the root of this repository, and then apply them by running:

```sh
source my.env
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

The site should now be live at http://localhost:8000

### Load a collection

```
uv run scripts/importers/library_of_virginia.py --area A
```

### Admin creds

You can login to `/admin` with the username & password: `admin`
