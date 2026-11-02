# One image for the API, the worker and the demo sink, chosen by command (D-020).
# Built from the repository root, because the mock extractor needs data/labeled:
#   docker build -f backend/Dockerfile .

FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock ./
# Dependencies first, so a source change does not reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY backend/src ./src
# Not editable: the runtime stage copies the environment without the source tree.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /nonexistent app \
    && mkdir -p /data/storage \
    && chown app:app /data/storage
COPY --from=build /app/.venv /app/.venv
COPY backend/alembic.ini /app/
COPY backend/migrations /app/migrations
COPY data/labeled /app/data/labeled
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    LABELS_DIR=/app/data/labeled \
    STORAGE_DIR=/data/storage
WORKDIR /app
USER 10001:10001
EXPOSE 8100
# No HEALTHCHECK here: the image runs as API, worker, sink and setup, and compose.yaml gives each
# role its own. A check disabled per service still counts as configured, and Compose 2.38 then
# fails `up --wait` on the worker.
# --no-proxy-headers: uvicorn would otherwise trust X-Forwarded-For from any local peer (D-042).
CMD ["uvicorn", "--factory", "intakefold.api.app:create_app", "--host", "0.0.0.0", "--port", "8100", "--no-proxy-headers"]
