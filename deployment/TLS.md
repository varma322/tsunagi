# Serving Tsunagi over HTTPS

Tsunagi carries SMS contents and bearer tokens, so anything beyond a local test
deployment needs TLS. The Android app enforces this: it refuses cleartext HTTP
to any address other than loopback, so a plain `http://` server URL fails rather
than silently sending your messages in the clear.

Pick the path that matches your deployment:

| Situation | Path |
|---|---|
| Public domain pointing at this host | [Let's Encrypt](#option-a-lets-encrypt-recommended) |
| LAN-only, no public DNS | [Private CA](#option-b-lan-only-with-a-private-ca) |
| Already behind Cloudflare Tunnel, Tailscale, or a company proxy | [Existing terminator](#option-c-tls-terminated-elsewhere) |

---

## Option A: Let's Encrypt (recommended)

**Prerequisites:** a domain whose A/AAAA record points at this host, and ports
80 and 443 reachable from the internet. Port 80 must stay open — it is how
renewals are validated.

### 1. Configure the domain

In `deployment/.env`:

```ini
TSUNAGI_DOMAIN=tsunagi.example.com
TSUNAGI_CORS_ORIGINS=https://tsunagi.example.com
```

### 2. Issue the first certificate

nginx will not start with the TLS config until the certificate exists, and
certbot cannot answer the challenge until nginx is serving. Break the deadlock
by issuing the certificate with a standalone listener first:

```bash
cd deployment
docker compose down

docker run --rm -p 80:80 \
  -v tsunagi_certbot-conf:/etc/letsencrypt \
  -v tsunagi_certbot-webroot:/var/www/certbot \
  certbot/certbot certonly --standalone \
  -d tsunagi.example.com \
  --email you@example.com --agree-tos --no-eff-email
```

Add `--staging` on the first attempt if you are unsure of the setup — Let's
Encrypt rate-limits failed issuance for production certificates, and a typo can
lock you out for a week. Re-run without `--staging` once it succeeds, adding
`--force-renewal`.

The volume names are prefixed with the compose project name (`tsunagi`); check
yours with `docker volume ls` if you renamed it.

### 3. Start the stack with TLS

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

This publishes 80 (redirect + ACME challenges) and 443, mounts the certificates
read-only into nginx, and runs a certbot container that renews twice a day.
nginx reloads every six hours so renewed certificates take effect.

### 4. Verify

```bash
curl -I https://tsunagi.example.com/health
curl -I http://tsunagi.example.com/health     # expect 301 to https
```

Then confirm renewal works before you rely on it:

```bash
docker compose exec certbot certbot renew --dry-run
```

### 5. Only then, consider HSTS

`tsunagi-tls.conf` sets `Strict-Transport-Security` with a two-year max-age.
This is a one-way door: browsers will refuse plain HTTP for your domain for that
long, and a lapsed certificate becomes a hard outage. Confirm the dry-run above
passes before leaving it enabled; comment the header out otherwise.

---

## Option B: LAN-only with a private CA

Public CAs will not issue for a private address, so create your own CA and trust
it on the phone. [mkcert](https://github.com/FiloSottile/mkcert) does this in
two commands:

```bash
mkcert -install
mkcert tsunagi.lan 192.168.1.50
```

Mount the resulting pair where the TLS config expects them, replacing the
certbot volumes in `docker-compose.tls.yml`:

```yaml
  nginx:
    volumes:
      - ./nginx/tsunagi-tls.conf:/etc/nginx/templates/default.conf.template:ro
      - ./certs/tsunagi.lan.pem:/etc/letsencrypt/live/tsunagi.lan/fullchain.pem:ro
      - ./certs/tsunagi.lan-key.pem:/etc/letsencrypt/live/tsunagi.lan/privkey.pem:ro
```

Drop the `certbot` service, since there is nothing to renew.

**On the phone:** install the mkcert root CA (`mkcert -CAROOT` shows where it
lives) via Settings → Security → Encryption & credentials → Install a
certificate → CA certificate. Without this the app rejects the connection, which
is the intended behaviour — an untrusted certificate is indistinguishable from
an interception attempt.

---

## Option C: TLS terminated elsewhere

If Cloudflare Tunnel, Tailscale Serve, Caddy, or a company load balancer already
terminates TLS, keep the base `docker-compose.yml` and point that terminator at
the published HTTP port. Two things still need attention:

- Set `TSUNAGI_CORS_ORIGINS` to the **public** `https://` origin, not the
  internal one.
- Make sure the terminator forwards WebSocket upgrades to `/ws/`, or the
  dashboard falls back to a disconnected state and stops updating live.

---

## After enabling TLS

Update the Android app's **Server URL** to the `https://` address. The app will
re-register if its token was issued against the old origin — that is expected;
messages already uploaded are unaffected.

Nothing else in the stack needs to change: the dashboard and API share an
origin, so the WebSocket automatically upgrades to `wss://` along with the page.
