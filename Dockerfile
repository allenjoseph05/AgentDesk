# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.14.6
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 10001 agentdesk \
    && useradd --system --uid 10001 --gid agentdesk --home-dir /app agentdesk

COPY requirements.lock pyproject.toml README.md alembic.ini ./
COPY agents ./agents
COPY fixtures ./fixtures
COPY packages ./packages
COPY scripts ./scripts

RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps .

USER agentdesk

EXPOSE 8000 8005 8006 8007

CMD ["python", "-m", "uvicorn", "agents.coordinator.main:app", "--host", "0.0.0.0", "--port", "8000"]
