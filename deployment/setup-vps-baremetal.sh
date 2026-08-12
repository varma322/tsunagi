#!/usr/bin/env bash
#
# Tsunagi installer for a VPS that already runs PostgreSQL, Redis and nginx.
#
# No Docker. Tsunagi runs as a systemd service on loopback, the dashboard is
# served as static files by the existing nginx, and the database and cache are
# the ones already on the box — which on srv1239365 means PostgreSQL 16 and
# Redis, saving roughly 200 MB against running duplicates in containers.
#
# It will NOT:
#   * touch existing databases, Redis keyspaces, nginx sites or services
#   * bind any public port (the API listens on 127.0.0.1 only)
#   * open firewall ports (nginx already has 80/443)
#   * regenerate secrets on a re-run
#
# Usage, as root on the VPS:
#   ./setup-vps-baremetal.sh --domain sms.example.com --email you@example.com
#   ./setup-vps-baremetal.sh --domain sms.example.com --dist /tmp/dist.tar.gz
#   ./setup-vps-baremetal.sh --domain sms.example.com --no-tls
#
# --dist takes a dashboard built elsewhere (a directory or a .tar.gz), which is
# the sensible route on a one-core box: build on your machine, ship the output.
# The build is plain static assets, so the OS that produced them does not
# matter -- a Windows build and a Linux build are byte-identical.
#
set -euo pipefail

REPO_URL="${TSUNAGI_REPO:-https://github.com/varma322/Tsunagi.git}"
INSTALL_DIR="${TSUNAGI_DIR:-/opt/tsunagi}"
SERVICE_USER="tsunagi"
ENV_DIR="/etc/tsunagi"
ENV_FILE="$ENV_DIR/tsunagi.env"
API_PORT="8095"
DOMAIN=""
EMAIL=""
WANT_TLS=1
BUILD_FRONTEND=1
DIST_SOURCE=""

log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[0;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[0;31mfailed:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email)  EMAIL="${2:-}";  shift 2 ;;
    --port)   API_PORT="${2:-}"; shift 2 ;;
    --no-tls) WANT_TLS=0; shift ;;
    --skip-build) BUILD_FRONTEND=0; shift ;;
    --dist) DIST_SOURCE="${2:-}"; BUILD_FRONTEND=0; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root"
[ -n "$DOMAIN" ] || die "--domain is required, e.g. --domain sms.example.com"
[ "$WANT_TLS" -eq 0 ] || [ -n "$EMAIL" ] || die "--email is required unless --no-tls"

# --------------------------------------------------------------------------
log "Preflight"

for tool in python3 git curl nginx psql redis-cli; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Python 3.11+ required, found $PY_VERSION"
python3 -c 'import venv' 2>/dev/null || die "python3-venv is missing: apt install python3-venv"
ok "python $PY_VERSION with venv"

systemctl is-active --quiet postgresql || die "postgresql is not running"
systemctl is-active --quiet nginx      || die "nginx is not running"
redis-cli ping >/dev/null 2>&1         || die "redis is not responding on the default socket"
ok "postgresql, redis and nginx are all up"

if ss -tuln | grep -qE "127.0.0.1:${API_PORT} |0.0.0.0:${API_PORT} |:::${API_PORT} "; then
  die "port ${API_PORT} is in use; pass --port with a free one"
fi
ok "127.0.0.1:${API_PORT} is free"

if [ "$BUILD_FRONTEND" -eq 1 ] && ! command -v npm >/dev/null; then
  die "npm is required to build the dashboard; pass --skip-build and upload frontend/dist yourself"
fi

# --------------------------------------------------------------------------
log "Swap"

# One core and under 2 GB free is exactly where `vite build` gets OOM-killed.
if [ "$(swapon --show --noheadings | wc -l)" -gt 0 ]; then
  ok "swap already present"
elif [ "$BUILD_FRONTEND" -eq 0 ]; then
  ok "not building on this host; skipping swap"
elif [ "$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)" -ge 3000 ]; then
  ok "enough free memory; skipping swap"
else
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
  ok "2G swap enabled and persisted"
fi

# --------------------------------------------------------------------------
log "Service account and source"

if id "$SERVICE_USER" >/dev/null 2>&1; then
  ok "user $SERVICE_USER exists"
else
  useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  ok "created system user $SERVICE_USER"
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --quiet --tags origin
  git -C "$INSTALL_DIR" pull --quiet --ff-only || warn "could not fast-forward; leaving the checkout alone"
  ok "updated $INSTALL_DIR"
else
  mkdir -p "$INSTALL_DIR"
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  ok "cloned into $INSTALL_DIR"
fi
[ -f "$INSTALL_DIR/backend/requirements-postgres.txt" ] || die "$INSTALL_DIR does not look like the Tsunagi repo"

# --------------------------------------------------------------------------
log "Python environment"

if [ -x "$INSTALL_DIR/backend/.venv/bin/python" ]; then
  ok "virtualenv exists"
else
  python3 -m venv "$INSTALL_DIR/backend/.venv"
  ok "created virtualenv"
fi
"$INSTALL_DIR/backend/.venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/backend/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/backend/requirements-postgres.txt"
ok "dependencies installed (including asyncpg)"

# --------------------------------------------------------------------------
log "PostgreSQL"

# A dedicated role and database. Existing databases are never touched.
DB_NAME="tsunagi"
DB_USER="tsunagi"

role_exists=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" || true)
db_exists=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" || true)

if [ "$role_exists" = "1" ] && [ "$db_exists" = "1" ]; then
  ok "role and database '${DB_NAME}' already exist"
  DB_PASSWORD=""   # reused from the existing env file below
else
  DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  if [ "$role_exists" != "1" ]; then
    su - postgres -c "psql -qc \"CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}'\"" >/dev/null
    ok "created role ${DB_USER}"
  else
    su - postgres -c "psql -qc \"ALTER ROLE ${DB_USER} PASSWORD '${DB_PASSWORD}'\"" >/dev/null
    warn "role existed without a database; its password was reset"
  fi
  if [ "$db_exists" != "1" ]; then
    su - postgres -c "createdb -O ${DB_USER} ${DB_NAME}"
    ok "created database ${DB_NAME} owned by ${DB_USER}"
  fi
fi

# --------------------------------------------------------------------------
log "Redis"

# Pick an unused logical database so Tsunagi's pub/sub cannot collide with the
# Celery broker or anything else already on this Redis.
USED_DBS="$(redis-cli INFO keyspace 2>/dev/null | sed -n 's/^db\([0-9]\+\):.*/\1/p' | tr '\n' ' ')"
REDIS_DB=""
for i in $(seq 1 15); do
  case " $USED_DBS " in *" $i "*) continue ;; esac
  REDIS_DB="$i"; break
done
[ -n "$REDIS_DB" ] || die "every Redis database 1-15 is in use; set TSUNAGI_REDIS_URL by hand"
ok "using redis database ${REDIS_DB} (in use: ${USED_DBS:-none})"

# --------------------------------------------------------------------------
log "Configuration"

mkdir -p "$ENV_DIR"

if [ -f "$ENV_FILE" ]; then
  ok "keeping the existing $ENV_FILE"
else
  [ -n "$DB_PASSWORD" ] || die "the database already existed but $ENV_FILE does not, so its password is unknown. Reset it with: su - postgres -c \"psql -c \\\"ALTER ROLE ${DB_USER} PASSWORD 'new'\\\"\" and write $ENV_FILE by hand."
  BOOTSTRAP_KEY="tsn_key_$(openssl rand -hex 24)"

  cat >"$ENV_FILE" <<ENV
# Generated by setup-vps-baremetal.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)

TSUNAGI_DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}
TSUNAGI_REDIS_URL=redis://127.0.0.1:6379/${REDIS_DB}

# Admin API key for the dashboard, pinned so it survives restarts.
TSUNAGI_BOOTSTRAP_API_KEY=${BOOTSTRAP_KEY}

# Devices enrol with single-use codes from the dashboard; the legacy shared
# setup key stays unset.
# TSUNAGI_SETUP_KEY=

# Alembic owns the schema here; the unit runs it before starting.
TSUNAGI_AUTO_CREATE_SCHEMA=false

TSUNAGI_CORS_ORIGINS=https://${DOMAIN}
ENV
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
  ok "wrote $ENV_FILE (0640 root:${SERVICE_USER})"
fi

ADMIN_KEY="$(grep -E '^TSUNAGI_BOOTSTRAP_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"

# --------------------------------------------------------------------------
log "Dashboard"

DIST="$INSTALL_DIR/frontend/dist"

if [ -n "$DIST_SOURCE" ]; then
  [ -e "$DIST_SOURCE" ] || die "--dist path not found: $DIST_SOURCE"
  rm -rf "$DIST"; mkdir -p "$DIST"
  if [ -d "$DIST_SOURCE" ]; then
    cp -a "$DIST_SOURCE/." "$DIST/"
  else
    # A tarball may or may not have a leading dist/ component; accept both.
    tmp="$(mktemp -d)"
    tar xzf "$DIST_SOURCE" -C "$tmp"
    if [ -d "$tmp/dist" ]; then cp -a "$tmp/dist/." "$DIST/"; else cp -a "$tmp/." "$DIST/"; fi
    rm -rf "$tmp"
  fi
  [ -f "$DIST/index.html" ] || die "no index.html under $DIST — is $DIST_SOURCE really a Vite build?"
  ok "installed the prebuilt dashboard from $DIST_SOURCE ($(find "$DIST" -type f | wc -l) files)"

elif [ "$BUILD_FRONTEND" -eq 0 ]; then
  if [ ! -f "$DIST/index.html" ]; then
    cat >&2 <<HINT

  $DIST does not exist. frontend/dist is gitignored, so a fresh clone never
  has it. Build on your own machine and ship the output:

      # on your machine, in the repo
      cd frontend && npm run build
      tar czf dist.tar.gz dist                 # or: scp -r dist root@host:/tmp/dist
      scp dist.tar.gz root@${DOMAIN}:/tmp/

      # then re-run here
      $0 --domain ${DOMAIN} --dist /tmp/dist.tar.gz

HINT
    die "no prebuilt dashboard found"
  fi
  ok "using the existing $DIST"
else
  cd "$INSTALL_DIR/frontend"
  # Cap the heap: the default is a fraction of total RAM, which on a 4 GB box
  # lets node grow until the OOM killer intervenes mid-build.
  export NODE_OPTIONS="--max-old-space-size=1024"
  npm ci --no-audit --no-fund --silent
  npm run build --silent
  unset NODE_OPTIONS
  ok "built $(du -sh "$DIST" | cut -f1) of static assets"
fi

# nginx (www-data) must be able to traverse and read the build output.
chmod o+rx "$INSTALL_DIR" "$INSTALL_DIR/frontend" 2>/dev/null || true
chmod -R o+rX "$DIST"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"

# --------------------------------------------------------------------------
log "systemd service"

UNIT="/etc/systemd/system/tsunagi-api.service"
TEMPLATE="$INSTALL_DIR/deployment/systemd/tsunagi-api.service"
[ -f "$TEMPLATE" ] || die "missing $TEMPLATE"

# One worker: the event bus and rate limiter are per-process without Redis, and
# with Redis configured more workers would be safe — but this box has one core,
# so a second worker would only add contention.
sed -e "s|--port 8000|--port ${API_PORT}|" "$TEMPLATE" >"$UNIT"

systemctl daemon-reload
systemctl enable --quiet tsunagi-api
systemctl restart tsunagi-api

printf '    waiting for the API'
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    printf '\n'; ok "healthy: $(curl -fsS "http://127.0.0.1:${API_PORT}/health")"
    break
  fi
  printf '.'; sleep 2
done
curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1 \
  || { journalctl -u tsunagi-api -n 30 --no-pager; die "the API did not come up"; }

# --------------------------------------------------------------------------
log "nginx site"

SITE="/etc/nginx/sites-available/tsunagi"

if [ -f "$SITE" ]; then
  ok "$SITE already exists; leaving it untouched"
else
  cat >"$SITE" <<NGINX
# Tsunagi — static dashboard off disk, API proxied to 127.0.0.1:${API_PORT}.
# certbot adds the TLS block and the port 80 redirect below.
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    root ${DIST};
    index index.html;

    client_max_body_size 2m;

    access_log /var/log/nginx/tsunagi.access.log;
    error_log  /var/log/nginx/tsunagi.error.log;

    # Hashed filenames, so these can be cached indefinitely.
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Never cache the shell, or a deploy strands clients on stale asset hashes.
    location = /index.html {
        add_header Cache-Control "no-cache";
    }

    # The dashboard's live feed needs the HTTP/1.1 upgrade dance, which
    # proxy_params does not provide.
    location /ws/ {
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
    }

    # GET /api/v1/messages/wait long-polls, so this must exceed its 60s ceiling.
    location /api/ {
        include proxy_params;
        proxy_pass http://127.0.0.1:${API_PORT};
        proxy_read_timeout 120s;
    }

    location = /health {
        include proxy_params;
        proxy_pass http://127.0.0.1:${API_PORT}/health;
        access_log off;
    }

    location ~ ^/(docs|redoc|openapi\.json) {
        include proxy_params;
        proxy_pass http://127.0.0.1:${API_PORT};
    }

    # Client-side routing: unknown paths render the app shell.
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX
  ln -sfn "$SITE" /etc/nginx/sites-enabled/tsunagi
  ok "created $SITE and enabled it"
fi

# Validate the whole config before reloading: a syntax error here would take
# down every other site on this box, not just Tsunagi.
if ! nginx -t 2>/dev/null; then
  rm -f /etc/nginx/sites-enabled/tsunagi
  nginx -t || true
  die "nginx config test failed; the Tsunagi site was unlinked and nothing was reloaded"
fi
systemctl reload nginx
ok "nginx validated and reloaded; existing sites untouched"

# --------------------------------------------------------------------------
if [ "$WANT_TLS" -eq 1 ]; then
  log "TLS"
  if [ -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    ok "a certificate for ${DOMAIN} already exists"
  elif ! command -v certbot >/dev/null; then
    warn "certbot is not installed; run: certbot --nginx -d ${DOMAIN}"
  elif certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --no-eff-email --redirect --non-interactive; then
    ok "certificate issued and nginx updated"
  else
    warn "certbot failed. If this record is proxied by Cloudflare with"
    warn "'Always Use HTTPS' on, the challenge is redirected before reaching"
    warn "this host: set the record to DNS-only, run"
    warn "  certbot --nginx -d ${DOMAIN}"
    warn "then re-enable the proxy."
  fi
fi

# --------------------------------------------------------------------------
log "Verifying"

if [ -f "$INSTALL_DIR/scripts/smoke_test.py" ]; then
  "$INSTALL_DIR/backend/.venv/bin/python" "$INSTALL_DIR/scripts/smoke_test.py" \
      --url "http://127.0.0.1:${API_PORT}" --api-key "$ADMIN_KEY" \
      || warn "smoke test reported failures (see above)"
fi

SCHEME="http"; [ -d "/etc/letsencrypt/live/${DOMAIN}" ] && SCHEME="https"

cat <<SUMMARY

$(printf '\033[1;32m')Tsunagi is installed (no Docker).$(printf '\033[0m')

  Dashboard   ${SCHEME}://${DOMAIN}
  Admin key   ${ADMIN_KEY}

  Sign in with that key, then Devices → Add a device to generate a
  single-use enrolment code for the phone.

  Source      ${INSTALL_DIR}
  Config      ${ENV_FILE}   (0640 — holds every secret)
  API         127.0.0.1:${API_PORT}  (loopback only; nginx fronts it)
  Database    postgresql://${DB_USER}@127.0.0.1/${DB_NAME}  (your existing server)
  Redis       127.0.0.1:6379/${REDIS_DB}  (your existing server)

  Logs        journalctl -u tsunagi-api -f
  Restart     systemctl restart tsunagi-api
  Update      cd ${INSTALL_DIR} && git pull \\
              && backend/.venv/bin/pip install -r backend/requirements-postgres.txt \\
              && (cd frontend && npm ci && npm run build) \\
              && systemctl restart tsunagi-api
  Backup      su - postgres -c "pg_dump ${DB_NAME}" | gzip > tsunagi-\$(date +%F).sql.gz

SUMMARY
