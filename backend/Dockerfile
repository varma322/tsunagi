FROM python:3.12-slim

# Pinned so an image rebuild resolves dependencies with the same resolver that
# produced uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/srv/tsunagi/.venv/bin:$PATH"

WORKDIR /srv/tsunagi

RUN adduser --disabled-password --gecos "" --uid 10001 tsunagi

# Built from the repository root, not backend/, so operational scripts can be
# shipped alongside the app. See the `api` service in deployment/.
#
# --frozen installs exactly what uv.lock pins and fails rather than re-resolving,
# so the image and a bare-metal `pip install -r requirements-postgres.txt` get
# the same versions. --no-install-project because the app is a virtual project:
# it is copied in below and imported from the working directory.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra postgres

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
