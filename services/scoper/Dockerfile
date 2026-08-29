# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14.6
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    SCOPER_FIXTURE_DIRECTORY=/app/fixtures/intake

WORKDIR /app

RUN groupadd --system --gid 10002 scoper \
    && useradd --system --uid 10002 --gid scoper --home-dir /app scoper

COPY services/scoper/requirements.lock ./services/scoper/requirements.lock
COPY services/scoper/pyproject.toml ./services/scoper/pyproject.toml
COPY services/scoper/src ./services/scoper/src
COPY fixtures/intake ./fixtures/intake
COPY packages ./packages

RUN python -m pip install --no-cache-dir -r services/scoper/requirements.lock \
    && python -m pip install --no-cache-dir --no-deps ./services/scoper

USER scoper

EXPOSE 8011

CMD ["python", "-m", "uvicorn", "agentdesk_scoper.main:app", "--host", "0.0.0.0", "--port", "8011"]
