# One container: FastAPI serves the API and the built React app on a single port.

# --- 1. Build the frontend -----------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- 2. Backend runtime --------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (read from pyproject.toml) so code changes don't
# invalidate this layer.
COPY backend/pyproject.toml backend/pyproject.toml
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('backend/pyproject.toml', 'rb'))['project']['dependencies']))" \
        > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY backend/app backend/app
COPY database database
COPY --from=frontend /app/frontend/dist frontend/dist

# The sample database is rebuilt from schema.sql + seed.sql at every build.
RUN python database/init_db.py \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p data \
    && chown -R appuser /app/data

USER appuser
WORKDIR /app/backend

# Render (and most hosts) provide PORT; 8000 is the local default.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
