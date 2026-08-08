# syntax=docker/dockerfile:1.7

FROM python:3.13.14-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.14-slim-bookworm AS runtime
ARG APP_VERSION=0.1.0
ARG CODE_COMMIT=unknown
ARG SOURCE_URL=https://github.com/sashkotenk/energy-consumption-forecasting-system

LABEL org.opencontainers.image.title="EnergyForecast backend" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${CODE_COMMIT}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARTIFACT_ROOT=/var/lib/energyforecast/artifacts

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 energyforecast \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin energyforecast \
    && mkdir -p /app /var/lib/energyforecast/artifacts \
    && touch /var/lib/energyforecast/artifacts/.volume-marker \
    && chown -R energyforecast:energyforecast /app /var/lib/energyforecast

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 alembic.ini ./alembic.ini
COPY --chown=10001:10001 migrations ./migrations

USER 10001:10001
EXPOSE 8000
CMD ["energy-forecast-api"]
