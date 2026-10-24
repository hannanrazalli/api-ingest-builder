FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
RUN npm install -g pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM python:3.12-slim-bookworm AS python-build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS base-runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY backend ./backend
COPY --from=frontend /ui/out ./frontend/out
RUN useradd --create-home app && mkdir /app/data && chown app:app /app/data \
    && chmod -R a+rX /app/backend /app/frontend
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base-runtime AS js
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN python -m ensurepip && python -m pip install --no-cache-dir playwright && python -m playwright install --with-deps chromium && chmod -R a+rX /opt/playwright
USER app

FROM base-runtime AS runtime
