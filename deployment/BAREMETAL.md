# Deploying Tsunagi without Docker

Docker is not required. This guide runs Tsunagi directly on a VPS with systemd,
nginx, PostgreSQL, and certbot — the classic stack. For the container route see
[VPS.md](VPS.md).

Examples use `sms.example.com`; substitute your own domain.

---

## Two things to know first

### Gunicorn alone will not work

Tsunagi is an **ASGI** application — async SQLAlchemy, long-polling, and
WebSockets. Gunicorn is a WSGI server and cannot run it directly. Your options:

```bash
# Uvicorn directly (recommended — one less moving part)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1

# Or gunicorn purely as a process manager around uvicorn workers
gunicorn app.main:app -k uvicorn.workers.UvicornWorker \
    --bind 127.0.0.1:8000 --workers 1
```

Both are equivalent in practice. Uvicorn supports multiple workers natively, so
gunicorn mainly buys you its process supervision — which systemd already
provides. The shipped unit file uses uvicorn.

### More than one worker requires Redis

This is the trap. Tsunagi's event bus and rate limiter fall back to
**per-process** state when `TSUNAGI_REDIS_URL` is unset. With `--workers 4` and
no Redis:

- A dashboard WebSocket connected to worker 2 never sees a message ingested by
  worker 3, so the live feed silently stops updating.
- `GET /api/v1/messages/wait` hangs until timeout instead of returning.
- Each worker enforces its own rate-limit budget, so the effective limit is
  four times what you configured.

So either run **one worker** (fine for a personal deployment — it is async, and
a single worker handles far more than a handful of phones produce), or install
Redis and set `TSUNAGI_REDIS_URL`.

---

## 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev \
    postgresql nginx certbot python3-certbot-nginx git
# Optional, needed only for multiple workers:
sudo apt install -y redis-server
```

Check your Python: `python3 --version`. 3.11 or newer is required.

## 2. Database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER tsunagi WITH PASSWORD 'change-me';
CREATE DATABASE tsunagi OWNER tsunagi;
SQL
```

## 3. Service account and code

```bash
sudo useradd --system --home /opt/tsunagi --shell /usr/sbin/nologin tsunagi
sudo mkdir -p /opt/tsunagi
sudo chown tsunagi:tsunagi /opt/tsunagi

sudo -u tsunagi git clone https://github.com/you/tsunagi.git /opt/tsunagi
```

## 4. Python environment

```bash
cd /opt/tsunagi/backend
sudo -u tsunagi python3 -m venv .venv
sudo -u tsunagi .venv/bin/pip install -r requirements-postgres.txt
```

`requirements-postgres.txt` pulls in `asyncpg`, the PostgreSQL driver. If your
Python is very new and no wheel exists, install `python3-dev` and a compiler
first, or use the distribution's Python rather than a bleeding-edge build.

## 5. Configuration

```bash
sudo mkdir -p /etc/tsunagi
sudo tee /etc/tsunagi/tsunagi.env >/dev/null <<'ENV'
TSUNAGI_DATABASE_URL=postgresql+asyncpg://tsunagi:change-me@localhost:5432/tsunagi
TSUNAGI_BOOTSTRAP_API_KEY=tsn_key_replace-with-a-generated-secret
TSUNAGI_CORS_ORIGINS=https://sms.example.com

# Devices are enrolled with single-use codes from the dashboard. Setting
# TSUNAGI_SETUP_KEY here would re-enable the older shared-password flow.

# Alembic owns the schema in production.
TSUNAGI_AUTO_CREATE_SCHEMA=false

# Uncomment together with --workers > 1 in the unit file.
# TSUNAGI_REDIS_URL=redis://localhost:6379/0
ENV

sudo chown root:tsunagi /etc/tsunagi/tsunagi.env
sudo chmod 640 /etc/tsunagi/tsunagi.env
```

Generate a real admin key:

```bash
echo "TSUNAGI_BOOTSTRAP_API_KEY=tsn_key_$(openssl rand -hex 24)"
```

## 6. Build the dashboard

The dashboard compiles to static files; nothing Node-related runs in production.

**On the server** (needs Node 20+, and roughly 1 GB free RAM for the build):

```bash
cd /opt/tsunagi/frontend
sudo -u tsunagi npm ci
sudo -u tsunagi npm run build     # writes dist/
```

**Or build on your laptop** and ship only the output, which keeps Node off the
server entirely:

```bash
cd frontend && npm run build
rsync -av dist/ you@server:/tmp/tsunagi-dist/
ssh you@server 'sudo rsync -av --delete /tmp/tsunagi-dist/ /opt/tsunagi/frontend/dist/ \
    && sudo chown -R tsunagi:tsunagi /opt/tsunagi/frontend/dist'
```

## 7. systemd service

```bash
sudo cp /opt/tsunagi/deployment/systemd/tsunagi-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tsunagi-api
sudo systemctl status tsunagi-api
```

The unit runs `alembic upgrade head` before starting, so migrations apply on
every restart and deploy.

Verify the API is listening locally before touching nginx:

```bash
curl -s localhost:8000/health
```

## 8. nginx

```bash
sudo cp /opt/tsunagi/deployment/nginx/tsunagi-baremetal.conf \
    /etc/nginx/sites-available/tsunagi
sudo sed -i 's/sms.example.com/sms.yourdomain.com/' /etc/nginx/sites-available/tsunagi
sudo ln -s /etc/nginx/sites-available/tsunagi /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t && sudo systemctl reload nginx
```

nginx serves the dashboard straight off disk and proxies `/api/`, `/ws/`,
`/health`, and `/docs` to uvicorn on localhost.

## 9. TLS

With DNS already pointing at this server:

```bash
sudo certbot --nginx -d sms.yourdomain.com
sudo certbot renew --dry-run
```

certbot rewrites the site file to add the TLS server block and the HTTP
redirect, and installs a renewal timer. Nothing else to configure.

## 10. Verify

```bash
curl -I https://sms.yourdomain.com/health
python scripts/smoke_test.py --url https://sms.yourdomain.com \
    --setup-key <setup key> --api-key <admin key>
```

Then point the Android app at `https://sms.yourdomain.com`.

---

## Operating it

```bash
# Logs
sudo journalctl -u tsunagi-api -f

# Restart after a config change
sudo systemctl restart tsunagi-api

# Mint an API key
cd /opt/tsunagi
sudo -u tsunagi backend/.venv/bin/python scripts/create_key.py --name laptop --scope admin

# Back up (PostgreSQL is the only durable state)
sudo -u postgres pg_dump tsunagi | gzip > ~/tsunagi-$(date +%F).sql.gz
```

### Updating

```bash
cd /opt/tsunagi
sudo -u tsunagi git pull
sudo -u tsunagi backend/.venv/bin/pip install -r backend/requirements-postgres.txt
cd frontend && sudo -u tsunagi npm ci && sudo -u tsunagi npm run build
sudo systemctl restart tsunagi-api     # runs migrations on start
```

Take a backup first.

---

## Docker or not?

Neither is wrong. Honest trade-offs:

**Bare metal is better when** you run one app on one server. nginx serves the
dashboard directly instead of proxying to a container, there is no Docker daemon
overhead (~150 MB of RAM back), logs land in journald with everything else, and
certbot's nginx plugin handles TLS with a single command instead of the
bootstrap dance containers require.

**Docker is better when** you want the deployment reproducible and disposable.
Migrations run automatically on start, rollback is retagging an image, and the
Python version is pinned by the image — that last one is not hypothetical: a
shadowed builtin in this codebase imports fine on Python 3.14 and crashes on
3.12, and the container caught it.

**The maintenance you take on with bare metal:** OS Python upgrades can break
the virtualenv, PostgreSQL major upgrades are yours to run, and you are
responsible for keeping the service account and file permissions right. None of
it is hard; it is simply not automatic.

For a personal Tsunagi install on a VPS you already manage, bare metal is a
completely reasonable choice.
