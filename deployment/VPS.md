# Deploying Tsunagi on a VPS

End-to-end walkthrough for putting Tsunagi on a public server with your own
domain. The examples use `sms.example.com` — substitute your own.

For TLS specifics beyond this walkthrough (private CA, an existing terminator
like Cloudflare Tunnel), see [TLS.md](TLS.md).

---

## What you need

- A VPS with a public IPv4 address. **2 GB RAM recommended** — the dashboard
  image compiles the frontend during build, which can exhaust a 1 GB box. On
  1 GB either add swap (below) or build images elsewhere.
- A domain you control, with DNS you can edit.
- SSH access with sudo.

---

## 1. Point DNS at the server

Create an **A record** for the subdomain:

| Type | Name | Value |
|------|------|-------|
| A    | sms  | your.vps.ip.address |

If you use Cloudflare, set the record to **DNS only** (grey cloud) for the
initial certificate issuance. You can enable proxying afterwards.

Confirm it resolves before continuing — certificate issuance fails otherwise:

```bash
dig +short sms.example.com
```

---

## 2. Prepare the server

```bash
ssh you@your.vps.ip

# Docker Engine + Compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in

# Firewall: SSH, HTTP, HTTPS. Port 80 must stay open — certificate
# renewals are validated over it.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

On a 1 GB server, add swap so the frontend build does not get OOM-killed:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 3. Get the code onto the server

**Via git** (push this repository to GitHub/GitLab first):

```bash
git clone https://github.com/you/tsunagi.git
cd tsunagi
```

**Or copy directly** from your development machine:

```bash
rsync -av --progress \
  --exclude node_modules --exclude .venv --exclude build \
  --exclude .gradle --exclude '*.db' --exclude .env \
  ./ you@your.vps.ip:~/tsunagi/
```

Only `backend/`, `frontend/`, `scripts/`, and `deployment/` are needed to run
the server; the Android sources are not.

---

## 4. Configure

```bash
cd ~/tsunagi/deployment
cp .env.example .env
```

Generate real secrets rather than editing the placeholders by hand:

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -base64 24)"
echo "TSUNAGI_BOOTSTRAP_API_KEY=tsn_key_$(openssl rand -hex 24)"
```

Then edit `.env` so it reads:

```ini
POSTGRES_USER=tsunagi
POSTGRES_PASSWORD=<generated>
POSTGRES_DB=tsunagi

TSUNAGI_BOOTSTRAP_API_KEY=tsn_key_<generated>

TSUNAGI_DOMAIN=sms.example.com
TSUNAGI_CORS_ORIGINS=https://sms.example.com
```

Leave `TSUNAGI_SETUP_KEY` unset. Phones are enrolled with single-use codes
generated on the dashboard, which expire in minutes and cannot be reused;
setting a setup key re-enables the older shared-password flow.

Setting `TSUNAGI_BOOTSTRAP_API_KEY` is optional but recommended: without it the
admin key is generated at first boot and printed to the log exactly once, and
only its hash is stored. Pinning it means you always know what it is.

Lock the file down — it holds every secret in the deployment:

```bash
chmod 600 .env
```

---

## 5. Issue the first certificate

nginx will not start without a certificate, and certbot cannot answer the
challenge until something is serving port 80. Break the deadlock by issuing it
with a standalone listener, before the stack is up:

```bash
docker run --rm -p 80:80 \
  -v tsunagi_certbot-conf:/etc/letsencrypt \
  -v tsunagi_certbot-webroot:/var/www/certbot \
  certbot/certbot certonly --standalone \
  -d sms.example.com \
  --email you@example.com --agree-tos --no-eff-email
```

Add `--staging` first if you are unsure — Let's Encrypt rate-limits failed
issuance, and a DNS typo can lock you out for a week. Re-run without
`--staging` (adding `--force-renewal`) once it succeeds.

---

## 6. Start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
```

First build takes a few minutes. Watch it come up:

```bash
docker compose ps
docker compose logs -f api
```

Five containers should be running: `nginx`, `frontend`, `api`, `postgres`,
`redis`. Only nginx publishes ports; PostgreSQL and Redis are reachable only on
the internal Docker network.

---

## 7. Verify

```bash
curl -I https://sms.example.com/health
curl -I http://sms.example.com/health        # expect 301 to https

curl -H "Authorization: Bearer $TSUNAGI_BOOTSTRAP_API_KEY" \
  https://sms.example.com/api/v1/stats
```

Run the full end-to-end check from your development machine:

```bash
python scripts/smoke_test.py --url https://sms.example.com \
    --setup-key <TSUNAGI_SETUP_KEY> --api-key <admin key>
```

Then confirm renewal works, **before** relying on it:

```bash
docker compose exec certbot certbot renew --dry-run
```

Open `https://sms.example.com`, paste the admin key, and the dashboard connects.

---

## 8. Point the phone at it

Open `https://sms.example.com`, sign in with the admin key, and go to
**Devices → Add a device**. Generate a code, then in the Android app enter:

- **Server URL:** `https://sms.example.com`
- **Device name:** anything
- **Enrolment code:** the code from the dashboard

Save, and it registers itself, then discards the code. The app requires HTTPS
for any non-loopback address, so this only works once TLS is live — which is the
intended behaviour.

---

## Operating it

### Get or rotate an API key

```bash
docker compose exec api python scripts/create_key.py --name laptop --scope admin
```

Add `--revoke-existing` to invalidate every other key at the same time, e.g. if
one has leaked.

### Back up

PostgreSQL is the only durable state; Redis holds nothing that matters.

```bash
docker compose exec -T postgres pg_dump -U tsunagi tsunagi \
  | gzip > ~/tsunagi-$(date +%F).sql.gz
```

Restore into an empty database with:

```bash
gunzip -c tsunagi-2026-08-12.sql.gz \
  | docker compose exec -T postgres psql -U tsunagi tsunagi
```

Copy backups off the server — a backup on the same disk is not a backup.

### Update

```bash
cd ~/tsunagi && git pull
cd deployment
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
```

Migrations run automatically on API start. Take a backup first.

### Logs

```bash
docker compose logs -f api        # ingestion, auth failures, sync events
docker compose logs -f nginx      # requests and TLS
```

The dashboard's Events page shows the same server-side activity without SSH.

---

## Troubleshooting

**Certificate issuance fails.** Check DNS resolves to this server
(`dig +short sms.example.com`) and that port 80 is open. If Cloudflare proxying
is on, turn it off until the certificate is issued.

**`port is already allocated`.** Something else is on 80 or 443 — often a
distro nginx or Apache. `sudo ss -tulpn | grep -E ':(80|443)'`, then stop it
(`sudo systemctl disable --now apache2`).

**Dashboard loads but shows a connection error.** `TSUNAGI_CORS_ORIGINS` must
match the public origin exactly, including `https://`. Restart the API after
changing it.

**Phone will not register.** Confirm `https://sms.example.com/health` works from
the phone's browser and that the setup key matches `.env` exactly. The app
rejects plain HTTP to any non-loopback address by design.

**Frontend build killed during `up --build`.** Out of memory — add swap (step 2)
or build the image on a larger machine and push it to a registry.
