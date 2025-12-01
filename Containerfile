FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get -y update && apt-get install -y --no-install-recommends git binutils libproj-dev gdal-bin

WORKDIR /app

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock,relabel=shared \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml,relabel=shared \
    uv sync --locked --no-install-project

ADD . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

CMD [ \
    "sh", "-c", \
    "uv run manage.py collectstatic --noinput && uv run uvicorn georeference_tool.asgi:application --host 0.0.0.0 --port 8000" \
]
