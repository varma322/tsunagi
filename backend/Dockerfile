FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/tsunagi

RUN adduser --disabled-password --gecos "" --uid 10001 tsunagi

# Built from the repository root, not backend/, so operational scripts can be
# shipped alongside the app. See the `api` service in deployment/.
COPY backend/requirements.txt backend/requirements-postgres.txt ./
RUN pip install --no-cache-dir -r requirements-postgres.txt

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
# So `docker compose exec api python scripts/create_key.py` works on a server
# with no Python toolchain of its own.
COPY scripts ./scripts
COPY backend/docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh && chown -R tsunagi:tsunagi /srv/tsunagi

USER tsunagi
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
