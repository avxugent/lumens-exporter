# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Prometheus exporter for [Lumens](https://www.mylumens.com/) VC-TR40/VC-TR40N PTZ auto-tracking
cameras — **narrow scope on purpose**: basic connectivity (`probe_success`) and firmware/software
version (`lumens_device_info`) only. No PTZ control, no video/streaming metrics. That scope was an
explicit request, not an oversight — don't expand it without checking first.

## Protocol history — read this, it explains why the code looks the way it does

The first draft of this exporter assumed an HTTP CGI interface documented in the **VC-TR41** CGI
Command Set spreadsheet (RS197) — a *different, newer sibling model* in Lumens' auto-tracking PTZ
line, used because no CGI documentation could be found publicly for VC-TR40 itself. That design
assumed `GET /command/inquiry.cgi?inqjs=system` with HTTP Digest auth.

**That assumption was wrong**, discovered by testing against a real device
(`cam9092001.private.ugent.be`):

```bash
$ curl -v --digest -u admin:9999 "http://cam9092001.private.ugent.be/command/inquiry.cgi?inqjs=system"
< HTTP/1.1 404 Not Found
< Server: lighttpd/1.4.64
```

VC-TR40 runs a completely different, older embedded web framework: a numeric-page-ID router
(`GET /fcgi/do?id=<n>`) with a cookie + encrypted-password login system (see `OnLogin()` /
`EncryptCookie()` in the device's own JS if you ever need to reverse-engineer the login flow —
not done here, not needed for this scope). TR40 and TR41 do **not** share the same CGI framework;
that was a documentation gap, not a safe assumption, and future work on *this specific device
family* should not reuse Lumens' VC-TR41/newer-model CGI docs without testing first.

**What was found instead, confirmed live, and what this exporter actually uses:**

- `GET /fcgi/do?id=1` — the login page. Returns HTTP 200 whether or not a session is authenticated
  (every `id=` value redirects back to this same login page when unauthenticated — confirmed by
  requesting several). This is the "basic connection" signal. Its HTML contains a hidden input:
  ```html
  <input id=hcAboutMeModelName type=hidden value='VC-TR40'>
  ```
  — the camera's model name, exposed with **no login required**.
- `GET /js/version.js` — a static asset, not gated by login at all:
  ```js
  var web_version = "TR40-1.0.3.9"
  ```
  — the version string the device's own web UI bundle publishes about itself. This is what
  `software_version` reports.
- **No serial number** is exposed unauthenticated. Checked directly: the login page's HTML has no
  serial/MAC-shaped hidden field, and requesting other `id=` values while unauthenticated just
  redirects back to the login page (`ThisPage="userLogin"` regardless of which `id` was requested).
  `ProbeResult.serial` exists but is never populated, on purpose — it's there so a future
  login-flow implementation has somewhere to put it, not a bug.

No authentication, no OpenBao, no username/password config exists in this exporter — there's
nothing here that needs a secret. An earlier design iteration added OpenBao/Digest-auth plumbing
(mirroring `pjlink-exporter`'s `bao.py` shape) based on the wrong CGI assumption above; it was
removed once live testing showed nothing to authenticate. **Do not add it back** — see the next
section for why.

### `web_version` vs. the real firmware version (VXA200) — investigated, deliberately not implemented

The camera's actual firmware build number (e.g. `VXA200`) is **not** `web_version`
(`TR40-1.0.3.9`) — it's a separate string on an "About" page that requires being logged in:
`GET /fcgi/do?id=5&id=1`. This was confirmed live: unauthenticated, that URL just redirects back
to the login page (`ThisPage="userLogin"`), same as every other `id=` value.

The login mechanism was reverse-engineered from the device's own JS (`OnLogin()` /
`EncryptCookie()` / `submit3()` in the login page's inline `<script>`):

1. `GET /fcgi/do?action=Encrypt&UserName=<esc>&Password=<esc>` — `<esc>` uses a custom scheme
   (`PostEncode`/`PostEncodeIncTimeSplit` in `js/common.js`: `` & `` → `` `B ``, `` = `` → `` `C ``,
   etc., *not* real encryption — the password travels essentially plaintext over HTTP). Returns
   `hcSingleResult` (an MD5-looking hash on success, literal `-1` on bad credentials).
2. `POST` back to the current URL, body `SubmitData=begin&Operation=CreateSession&DestURL=<hcDestURL
   value, same custom-escaped form>&SubmitData=end`.

**This was tested live against the real camera** with valid credentials (`admin`/`9999`, the
device's documented default — confirmed correct, `hcSingleResult` came back a real hash, not
`-1`). No `Set-Cookie` was ever issued by either request (confirmed via raw headers and by
replaying the whole sequence over one persistent `http.client` connection) — this device does not
appear to use cookie- or connection-bound sessions at all for this flow, and the exact mechanism
that's supposed to grant access afterward was not pinned down. More importantly: after this one
login attempt, the POST response came back with `hcLoginStatus = -2` — the device's own
*"limited login"* / anti-flood code (`LoginLimitedWarning` in its JS) — triggered by just a
handful of test requests in quick succession.

**That finding is the reason this exporter does not implement the login flow, and should not,
without a very deliberate design for it**: a Prometheus exporter re-authenticating on every scrape
(every 15–60s, typically) would almost certainly retrigger this exact anti-flood protection in
production — and since it's the *same* login mechanism a human admin uses, that risks locking
*them* out of the web UI too, not just failing a metric. This was a live-tested, real finding
against production hardware (`cam9092001.private.ugent.be`), not a theoretical concern.

**The explicit decision, made with the user, was to keep this exporter unauthenticated** and treat
`web_version` as a proxy for firmware currency: the working assumption is that each firmware
release ships its own `web_version` string, so tracking `web_version` drift across the fleet is
good enough to notice "this device hasn't been updated" even though the displayed string isn't the
literal `VXA...` build number a human sees on the About page. If this proxy ever turns out to be
unreliable (e.g. a firmware update that doesn't bump `web_version`), revisit this tradeoff
explicitly — don't just add the login flow back in to "fix" it without re-deriving a safe request
pattern (e.g. authenticate at most once per exporter *process lifetime*, cache whatever grants
access, and treat any `-2` response as "stop and back off," not "retry").

Sibling exporters in this fleet: `pearl-exporter` (Sanic + HTTP API, Epiphan Pearl),
`pjlink-exporter` (stdlib http.server, raw TCP socket, cross-vendor projector protocol),
`lw3-exporter` (stdlib http.server, WebSocket, Lightware), `gude-exporter` (stdlib http.server,
HTTP/JSON, Gude), and `extronsis-exporter` (stdlib http.server, HTML scraping, no auth, Extron).
This repo ended up closest to **`extronsis-exporter`**'s shape — scraping a known HTML element
from an unauthenticated page — rather than the auth-heavy pattern it started from.

## Commands

```bash
# Install deps (PyYAML, prometheus-client)
pip install -r requirements.txt

# Run locally
cp config.example.yaml config.yaml   # edit devices
python -m lumens_exporter -c config.yaml

# CLI flags override config file values
python -m lumens_exporter -c config.yaml --host 0.0.0.0 --port 9881 --log-level DEBUG

# Docker
docker build -t lumens-exporter .
docker compose up -d
```

There is **no test suite, linter, or type-checker configured** in this repo (matching the rest of
the fleet). The only CI job (`.github/workflows/docker.yml`) builds and pushes a multiarch Docker
image to Docker Hub on push to `main`. Verify changes by running the exporter and curling its
endpoints:

```bash
curl "http://localhost:9881/probe?host=cam9092001.private.ugent.be&name=test"
```

Absent network access to a real camera, stand up a throwaway loopback HTTP stub serving
`/fcgi/do?id=1` (with the `hcAboutMeModelName` hidden input) and `/js/version.js` (with the
`web_version` assignment), and confirm `probe_device()` in `prober.py` extracts both — there's no
pure parsing entry point separate from the HTTP I/O.

## Architecture

Three files under `lumens_exporter/` (no `bao.py` — nothing to authenticate):

- **`prober.py`** — `probe_device(host, port=80, timeout=10.0)`: issues `GET /fcgi/do?id=1`
  (the "basic connection" check — success as soon as it returns HTTP 200), extracts
  `hcAboutMeModelName`'s value via `_MODEL_RE`, then — independently, best-effort, never flips a
  successful probe to failed — issues `GET /js/version.js` and extracts `web_version` via
  `_VERSION_RE`. No connection pooling — fresh connection per probe, matching the rest of the
  fleet. See the module docstring and "Protocol history" above for the full live-testing story.

- **`collector.py`** — `LumensCollector(prometheus_client.registry.Collector)`: turns
  `ProbeResult`s into Prometheus metric families (`probe_success`, `probe_duration_seconds`,
  `lumens_device` info). `collect()` runs fresh on every scrape (no caching), probing every
  configured device sequentially. Per-device failures don't abort the whole scrape.

- **`__main__.py`** — config loading (`load_config`, YAML + defaults merge), the HTTP handler
  (`_make_handler` closes over the loaded `cfg` dict), and `main()`/CLI argument parsing. Routes:
  `/` (HTML index), `/probe`, `/metrics`, `/healthz`. No credential resolution step — device dicts
  need only `name`, `host`, `port`, `timeout`.

### The two probing modes (both always active, can combine)

- **Config-file mode**: plain `GET /probe` scrapes every device listed under `devices:` in the
  YAML config.
- **URL-parameter mode**: `GET /probe?host=...&name=...` scrapes a single device described
  entirely by query params — no config-file entry needed. `_device_from_query_params()` in
  `__main__.py` builds the device dict; only `host` is required, everything else falls back to
  `_DEVICE_DEFAULTS`.

If a request supplies `host` as a query param, URL-parameter mode wins for that request even if
`devices:` is also configured — the two modes are per-request, not mutually exclusive globally.

### `/metrics` vs `/probe` — do not confuse these

- `/probe` returns **device** metrics (`probe_*`, `lumens_device_info`), built from a fresh
  `CollectorRegistry` + `LumensCollector` per request.
- `/metrics` returns the **exporter's own** self-metrics (`lumens_exporter_probe_requests_total`,
  `lumens_exporter_probe_duration_seconds`, plus default process/platform collectors) from
  `prometheus_client`'s global `REGISTRY`. It does not touch any device.

### Adding a new metric

1. A field obtainable from `/fcgi/do?id=1` or `/js/version.js` without login: add it to
   `ProbeResult` in `prober.py`, extract it alongside `model`/`software_version`, then add it to
   the `info` dict built in `collector.py`'s `collect()`.
2. A field that requires being logged in (e.g. serial number, likely on an "About" page): this
   needs the login flow implemented first — cookie handling plus whatever `EncryptCookie()` does
   to the password client-side (not reverse-engineered yet). That's a prober.py rewrite, not an
   extension; look at the real device's `OnLogin()`/`EncryptCookie()` JS functions as the starting
   point if this becomes necessary.
3. A PTZ-control or video/streaming metric: explicitly out of scope per this exporter's stated
   purpose — confirm that's actually wanted before building it.

`InfoMetricFamily(name, ...)` renders as `<name>_info` in the exposition format — the family is
registered as `"lumens_device"` in `collector.py` but shows up as `lumens_device_info` in scrape
output.

## Configuration

`config.yaml` is gitignored (contains internal hostnames) — `config.example.yaml` is the tracked
template and also what gets baked into the Docker image as the built-in default
(`/etc/lumens-exporter/config.yaml`, overridable via the `LUMENS_CONFIG` env var or by
bind-mounting over that path). The `devices:` list is optional at every level — an exporter with
zero configured devices is valid and simply requires every `/probe` call to pass `host`.

Transport is HTTP-only on port 80 (confirmed live — the camera's web UI and both scraped resources
are plain HTTP, no redirect to HTTPS observed).
