# Yesterdays

A Django web application for georeferencing historical images.

## Local development

To run georeference-tool locally, you need [`uv`](https://docs.astral.sh/uv/) and a PostgreSQL
database with pgvector and postgis.

### Run Database

The recommended way to run your database is using podman and
[MapRVA/cnpg-postgis-pgvector](https://github.com/MapRVA/cnpg-postgis-pgvector).

```
podman run -d --replace --name georef-postgres -e POSTGRES_DB=georef -e POSTGRES_USER=django_user -e POSTGRES_PASSWORD=dev_password -p 5432:5432 ghcr.io/maprva/postgis-pgvector-local:latest
```

### Set up environment variables

Setup the following env vars:

```
export LOCAL_DEV=1
export ALLOW_HARDCODED_ADMIN=1
export DJANGO_DEBUG=1
export PG_DBNAME=georef
export PG_USER=django_user
export PG_PASSWORD=dev_password
export PG_HOST=localhost
export PG_PORT=5432
export PG_SSL_MODE=disable
```

### Install dependencies
```
uv sync
```

### Apply migrations

```
uv run manage.py migrate
```

### Run the dev server!

```
uv run manage.py runserver
```

### Load a collection

```
uv run scripts/importers/library_of_virginia.py --area A
```

### Admin creds

You can login to `/admin` with the username & password: `admin`
