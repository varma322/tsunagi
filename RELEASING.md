# Releasing Tsunagi

Checklist for cutting a release. Versions live in four places and must agree.

---

## 1. Bump the version

| File | Field |
|---|---|
| `backend/app/__init__.py` | `__version__` |
| `backend/pyproject.toml` | `version` |
| `frontend/package.json` | `version` |
| `app/build.gradle.kts` | `versionName`, and **increment `versionCode`** |

`versionCode` must increase on every Android release, even a patch — Android
refuses to install an APK whose code is not higher than the installed one.

The API reports `__version__` at `GET /health`, which is how you confirm what a
server is actually running.

## 2. Update the changelog

Add a section to [CHANGELOG.md](CHANGELOG.md) with the date and what changed.
Note anything that breaks an existing deployment: a migration that cannot be
reversed, a scope that tightened, a configuration default that flipped.

## 3. Run everything

```bash
cd backend && .venv/Scripts/python -m pytest      # 79 tests
cd frontend && npm run typecheck && npm run build
./gradlew :app:testDebugUnitTest                  # 18 tests
```

Verify migrations round-trip, not just apply:

```bash
cd backend
TSUNAGI_DATABASE_URL=sqlite+aiosqlite:///./_rel.db .venv/Scripts/python -m alembic upgrade head
TSUNAGI_DATABASE_URL=sqlite+aiosqlite:///./_rel.db .venv/Scripts/python -m alembic downgrade base
rm _rel.db
```

Then bring the real stack up and smoke it — the container runs a different
Python version than most development machines, and has caught import-time
breakage that every local test missed:

```bash
cd deployment && cp .env.example .env
docker compose up -d --build && docker compose ps
python ../scripts/smoke_test.py --url http://127.0.0.1:8080 --api-key <admin key>
docker compose down -v
```

## 4. Build the Android release

Release builds are signed only when `keystore.properties` exists at the
repository root. Without it the build still succeeds and produces
`app-release-unsigned.apk`, which is fine for testing but not for distribution —
Android will not install an unsigned APK.

**Creating a signing key** (once, ever — losing it means you can never ship an
update that upgrades an existing install):

```bash
keytool -genkeypair -v -keystore tsunagi-release.jks -storetype PKCS12 \
    -keyalg RSA -keysize 4096 -validity 10000 -alias tsunagi
```

Run it from the repository root, so the keystore lands where
`keystore.properties` resolves it.

> **`keytool` is not on PATH on Windows.** It ships with the JDK, but the Oracle
> `javapath` shim exposes only `java` and `javac`. Find a real one:
>
> ```powershell
> Get-ChildItem "C:\Program Files\Java" -Directory |
>   ForEach-Object { Join-Path $_.FullName "bin\keytool.exe" } |
>   Where-Object { Test-Path $_ }
> ```
>
> Android Studio also bundles one at
> `C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe`. Any JDK works —
> the keystore format is not tied to the JDK that made it. Invoke it with the
> call operator, since the path has spaces:
>
> ```powershell
> & "C:\Program Files\Java\jdk-26.0.1\bin\keytool.exe" -genkeypair -v `
>     -keystore tsunagi-release.jks -storetype PKCS12 `
>     -keyalg RSA -keysize 4096 -validity 10000 -alias tsunagi
> ```

Then create `keystore.properties` at the repository root:

```ini
storeFile=tsunagi-release.jks
storePassword=…
keyAlias=tsunagi
keyPassword=…
```

Both the keystore and this file are gitignored. **Back them up somewhere other
than this machine.** There is no recovery: a lost key means future versions
cannot be installed as upgrades, only as a fresh install after uninstalling.

```bash
./gradlew :app:assembleRelease
# app/build/outputs/apk/release/app-release.apk
```

Install the APK on a real device and confirm the whole path works before
publishing: grant SMS permission, enrol with a code from the dashboard, send
yourself a message, and watch it land.

## 5. Tag and publish

```bash
git tag -a v1.0.0 -m "Tsunagi 1.0.0"
git push origin v1.0.0
```

Attach to the release:

- `app-release.apk` — the signed Android app
- The changelog section for this version

Server-side there is nothing to publish: deployments build from source with
`docker compose up -d --build`.

## 6. After releasing

Upgrading a deployment applies migrations automatically on API start. Tell
users to back up PostgreSQL first:

```bash
docker compose exec -T postgres pg_dump -U tsunagi tsunagi | gzip > backup.sql.gz
```
