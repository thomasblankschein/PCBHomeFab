# PCBHomeFab panel service. Build context: this folder.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . \
    && useradd --system --uid 10001 --home-dir /nonexistent --no-create-home app

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "panel.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
