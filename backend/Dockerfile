ARG PYTHON_IMAGE=python:3.13-slim
FROM ${PYTHON_IMAGE}
ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=${VCS_REF}
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.5
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY data/demo/seed.json ./data/demo/seed.json
RUN uv sync --locked --no-dev --no-editable \
    && rm -rf /app/src \
    && useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD [".venv/bin/uvicorn", "calorie_app.main:create_app", "--factory", "--host", "0.0.0.0", "--no-access-log"]
