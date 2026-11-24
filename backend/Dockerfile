FROM python:3.12-slim

# libgomp1: LightGBM and XGBoost need the OpenMP runtime, which the slim image lacks.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# A generous download timeout and retries: the dependency set is large (scipy, statsmodels, shap, lightgbm...).
ENV UV_HTTP_TIMEOUT=600 \
    UV_HTTP_RETRIES=5 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

COPY backend/ .
# The app resolves config/ and data/ one level above the backend folder (see ROOT in app/config.py). In this image that is /.
# docker-compose mounts the host's ./data over /data, which also holds the SQLite database.
COPY config /config
COPY data /data

# Run the installed environment directly: `uv run` would try to re-resolve at start-up.
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
