#!/usr/bin/env bash
#
# Update a bare-metal Tsunagi install in place.
#
# Works out what actually changed and does only that: dependencies are
# reinstalled when requirements move, migrations run when a new revision
# appears, and it tells you when the dashboard needs rebuilding rather than
# silently serving stale assets.
#
# Usage, as root on the VPS:
#   /opt/tsunagi/deployment/update.sh
#   /opt/tsunagi/deployment/update.sh --dist /tmp/dist.tar.gz   # ship a new dashboard too
#
set -euo pipefail

INSTALL_DIR="${TSUNAGI_DIR:-/opt/tsunagi}"
SERVICE_USER="tsunagi"
DIST_SOURCE=""

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mfailed:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dist) DIST_SOURCE="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root"
[ -d "$INSTALL_DIR/.git" ] || die "$INSTALL_DIR is not a git checkout"

git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

# --------------------------------------------------------------------------
log "Fetching"

BEFORE="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
git -C "$INSTALL_DIR" fetch --quiet --tags origin
git -C "$INSTALL_DIR" pull --quiet --ff-only || die "could not fast-forward; resolve the checkout by hand"
AFTER="$(git -C "$INSTALL_DIR" rev-parse HEAD)"

if [ "$BEFORE" = "$AFTER" ] && [ -z "$DIST_SOURCE" ]; then
  ok "already up to date at $(git -C "$INSTALL_DIR" log --oneline -1)"
  exit 0
fi
ok "$(git -C "$INSTALL_DIR" log --oneline -1)"

CHANGED="$(git -C "$INSTALL_DIR" diff --name-only "$BEFORE" "$AFTER" 2>/dev/null || true)"
changed_in() { printf '%s\n' "$CHANGED" | grep -q "^$1" ; }

# --------------------------------------------------------------------------
log "Applying what changed"

# A dump before any migration, since that is the only irreversible step here.
if printf '%s\n' "$CHANGED" | grep -q "^backend/alembic/versions/"; then
  BACKUP="/root/backup/pre-update-$(date +%Y%m%d-%H%M%S).sql.gz"
  mkdir -p /root/backup
  su - postgres -c "pg_dump tsunagi" | gzip > "$BACKUP"
  ok "new migrations detected; database dumped to $BACKUP"
fi

if changed_in "backend/requirements"; then
  "$INSTALL_DIR/backend/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/backend/requirements-postgres.txt"
  ok "python dependencies updated"
else
  ok "python dependencies unchanged"
fi

DIST="$INSTALL_DIR/frontend/dist"
if [ -n "$DIST_SOURCE" ]; then
  [ -e "$DIST_SOURCE" ] || die "--dist path not found: $DIST_SOURCE"
  rm -rf "$DIST"; mkdir -p "$DIST"
  if [ -d "$DIST_SOURCE" ]; then
    cp -a "$DIST_SOURCE/." "$DIST/"
  else
    tmp="$(mktemp -d)"; tar xzf "$DIST_SOURCE" -C "$tmp"
    if [ -d "$tmp/dist" ]; then cp -a "$tmp/dist/." "$DIST/"; else cp -a "$tmp/." "$DIST/"; fi
    rm -rf "$tmp"
  fi
  [ -f "$DIST/index.html" ] || die "no index.html under $DIST"
  ok "dashboard replaced from $DIST_SOURCE"
elif changed_in "frontend/"; then
  warn "the dashboard source changed but no --dist was given, so the site is"
  warn "still serving the old build. Rebuild on your machine and re-run:"
  warn "    cd frontend && npm run build && tar czf dist.tar.gz dist"
  warn "    scp dist.tar.gz root@<host>:/tmp/ && $0 --dist /tmp/dist.tar.gz"
else
  ok "dashboard unchanged"
fi

chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
chmod o+rx "$INSTALL_DIR" "$INSTALL_DIR/frontend" 2>/dev/null || true
[ -d "$DIST" ] && chmod -R o+rX "$DIST"

# --------------------------------------------------------------------------
log "Restarting"

# The unit runs `alembic upgrade head` before starting, so migrations apply here.
systemctl restart tsunagi-api

PORT="$(grep -oP -- '--port \K[0-9]+' /etc/systemd/system/tsunagi-api.service || echo 8095)"
printf '    waiting'
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    printf '\n'; ok "healthy: $(curl -fsS "http://127.0.0.1:${PORT}/health")"
    break
  fi
  printf '.'; sleep 2
done
curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 || {
  journalctl -u tsunagi-api -n 30 --no-pager
  die "the API did not come back up"
}

if changed_in "app/"; then
  warn "the Android app changed in this update. Rebuild and reinstall the APK,"
  warn "or the phone keeps running the old client:  ./gradlew :app:assembleRelease"
fi

log "Done"
git -C "$INSTALL_DIR" log --oneline -1 | sed 's/^/    now at /'
