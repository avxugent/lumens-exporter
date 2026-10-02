# Lumens Exporter

A Prometheus exporter for [Lumens](https://www.mylumens.com/) VC-TR40/VC-TR40N PTZ auto-tracking
cameras, written in Python. Scope is deliberately narrow right now: **basic connectivity and
firmware version only** — no PTZ control, no video/streaming metrics.

The exporter talks to the camera's **unauthenticated HTTP login page** (`GET /fcgi/do?id=1`) and
its static **`version.js`** asset — both verified live against a real VC-TR40
(`cam9092001.private.ugent.be`). No credentials are needed: the camera exposes its model name and
web UI version string without logging in. It's read-only: this exporter reports metrics, it does
not control the camera.

> Earlier drafts of this exporter assumed an HTTP CGI interface documented for the **VC-TR41**
> (a different sibling model) — that endpoint (`/command/inquiry.cgi`) does not exist on real
> VC-TR40 firmware. See `CLAUDE.md` for the full story and what was found instead.

## Usage

### Docker

#### Build

```bash
docker build -t lumens-exporter .
```

#### Run

```bash
docker run -p 9881:9881 lumens-exporter
```

### Manual

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

2.  Copy the example config and edit it:
    ```bash
    cp config.example.yaml config.yaml
    ```

3.  Run the exporter:
    ```bash
    python -m lumens_exporter -c config.yaml
    ```

    CLI flags override config file values:
    ```bash
    python -m lumens_exporter -c config.yaml --host 0.0.0.0 --port 9881 --log-level DEBUG
    ```

## Metrics

The exporter exposes device metrics on the `/probe` endpoint.

**Config-file mode** — scrapes every device listed in `config.yaml`:

```bash
curl "http://localhost:9881/probe"
```

**URL-parameter mode** — probes a single device by query parameter, no config-file entry needed
(useful for driving many devices via Prometheus `relabel_configs`, blackbox-exporter style):

```bash
curl "http://localhost:9881/probe?host=192.168.1.10&name=cam-room-101"
```

Both modes are always available; a request with a `host` parameter always wins for that request.

### Exposed Metrics

-   `probe_success`: 1 if the device's login page responded, 0 otherwise.
-   `probe_duration_seconds`: How long the probe took to complete.
-   `lumens_device_info` (info metric): device identity (`model`, `software_version`), scraped
    best-effort from the camera's login page and `version.js` — see `CLAUDE.md` for why this is
    best-effort rather than guaranteed, and why there's no `serial` field.

All device metrics carry `device` (the configured name) and `host` labels.

### Exporter self-metrics

`/metrics` returns the exporter's own process metrics (not any device's), for monitoring the
exporter itself: `lumens_exporter_probe_requests_total`, `lumens_exporter_probe_duration_seconds`,
plus the default Python/process collectors.

## Notes

- Devices are probed fresh on every scrape — no caching, no persistent connections.
- No credentials, no OpenBao integration — nothing this exporter queries requires authentication.
- This exporter's HTTP scraping targets (`/fcgi/do?id=1`'s `hcAboutMeModelName` hidden field,
  `js/version.js`'s `web_version` variable) were confirmed live against a real VC-TR40. If a
  firmware update changes either page's shape, `prober.py`'s regexes are the first place to check
  — see `CLAUDE.md`.
- `software_version` is the web UI bundle version (`web_version`, e.g. `TR40-1.0.3.9`), used as a
  proxy for the real firmware build number (e.g. `VXA200`), not the literal string shown on the
  camera's About page. That page requires logging in, and login was deliberately **not**
  implemented: live testing showed the device's own anti-flood protection triggers after just a
  few login attempts, which would risk locking out real admins if an exporter re-authenticated
  every scrape. See `CLAUDE.md` for the full investigation and why this is a considered tradeoff,
  not a shortcut.
