#!/bin/sh
set -e

# Alembic owns the schema in a container deployment; the app's create_all path
# is for local development only.
export TSUNAGI_AUTO_CREATE_SCHEMA="${TSUNAGI_AUTO_CREATE_SCHEMA:-false}"

echo "Applying database migrations..."
alembic upgrade head

exec "$@"
