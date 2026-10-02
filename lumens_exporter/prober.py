"""
Lumens VC-TR40/VC-TR40N PTZ auto-tracking camera prober.

**Verified against a real device** (cam9092001.private.ugent.be) — unlike
most of this fleet's other exporters. The CGI interface originally assumed
here (``/command/inquiry.cgi?inqjs=system``, HTTP Digest auth, documented in
the *VC-TR41* CGI Command Set spreadsheet — a different sibling model) does
**not** exist on real VC-TR40 firmware: that endpoint 404s. VC-TR40 runs a
different, older embedded web framework entirely: a numeric-page-ID router
(``GET /fcgi/do?id=<n>``, served by lighttpd) with a cookie + encrypted-
password login system that was not reverse-engineered here, because it
isn't needed for this exporter's narrow scope.

Two things are exposed **without any authentication**, confirmed live:

- ``GET /fcgi/do?id=1`` — the login page. Always returns HTTP 200 whether or
  not a session is logged in (every ``id=`` value redirects back to this
  same login page when unauthenticated — confirmed by probing several).
  Serves as the "basic connection" signal. Its HTML contains a hidden input
  ``hcAboutMeModelName`` whose ``value`` is the camera's model name (e.g.
  ``VC-TR40``).
- ``GET /js/version.js`` — a static asset, not gated by login at all.
  Contains ``var web_version = "TR40-1.0.3.9";`` — the version string the
  device's own web UI bundle publishes about itself. This is the practical
  "firmware version" signal available without credentials; it may not be
  the exact canonical firmware build number (that could differ, and might
  only be visible on an "About" page behind login), but it's what's
  reachable without implementing the login flow, which is out of scope for
  this exporter's current (connectivity + version) scope.

No serial number is exposed unauthenticated — confirmed by checking the
login page's HTML for any serial/MAC-shaped field (none found). That field
stays ``None`` until/unless a login flow is implemented.

Connectivity and field-extraction are independent concerns, same as the
rest of this fleet: a probe is successful as soon as ``/fcgi/do?id=1``
returns HTTP 200 (reachable), regardless of whether the model/version
extraction below finds what it's looking for.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 80

# Both pages are small; cap the read so a misbehaving device can't make us
# buffer an unbounded body (same defensive pattern as this fleet's other
# HTTP-based probers).
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_MODEL_RE = re.compile(r"hcAboutMeModelName[^>]*value=['\"]([^'\"]*)['\"]")
_VERSION_RE = re.compile(r'var\s+web_version\s*=\s*"([^"]*)"')


@dataclass
class ProbeResult:
    """Result of probing a single Lumens VC-TR40/VC-TR40N over HTTP."""

    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0

    model: Optional[str] = None
    serial: Optional[str] = None  # never populated without a login flow (see module docstring)
    software_version: Optional[str] = None


class _ProtocolError(ValueError):
    """Well-formed HTTP response, but not a shape this prober can parse."""


def _get(url: str, timeout: float) -> str:
    """Plain unauthenticated GET, capped and decoded. Raises on any failure."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        status = resp.status
        body = resp.read(_MAX_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")
    if len(body) > _MAX_RESPONSE_BYTES:
        raise _ProtocolError("response exceeded maximum size")
    if status != 200:
        raise _ProtocolError(f"unexpected HTTP status {status}")
    return body


def probe_device(
    host: str,
    port: int = DEFAULT_PORT,
    timeout: float = 10.0,
) -> ProbeResult:
    """
    Probe a Lumens VC-TR40/VC-TR40N for basic reachability and identity.

    Connectivity/HTTP failures on the primary request (the login page) are
    caught and reported via ProbeResult.success / .error rather than
    raised, so callers can always emit a probe_success metric. The
    secondary request (version.js) is independently best-effort: its
    failure is logged but never flips a successful probe to failed.
    """
    start = time.monotonic()
    result = ProbeResult()
    base = f"http://{host}:{port}"

    try:
        login_page = _get(f"{base}/fcgi/do?id=1", timeout)
        result.success = True  # reachable; field extraction below is best-effort

        match = _MODEL_RE.search(login_page)
        if match:
            result.model = match.group(1).strip() or None
        else:
            logger.warning(
                "Connected to %s:%d but could not find hcAboutMeModelName "
                "in the login page — the HTML this prober expects may have "
                "changed; see prober.py's module docstring",
                host, port,
            )
    except urllib.error.HTTPError as exc:
        result.error = f"HTTP {exc.code}: {exc.reason}"
        logger.warning("Probe failed for %s:%d: %s", host, port, result.error)
    except (urllib.error.URLError, OSError, TimeoutError, _ProtocolError) as exc:
        result.error = str(exc)
        logger.warning("Probe failed for %s:%d: %s", host, port, exc)
    finally:
        result.duration_seconds = time.monotonic() - start

    if result.success:
        try:
            version_js = _get(f"{base}/js/version.js", timeout)
            match = _VERSION_RE.search(version_js)
            if match:
                result.software_version = match.group(1).strip() or None
            else:
                logger.warning(
                    "Connected to %s:%d but could not find web_version in "
                    "js/version.js — the asset this prober expects may "
                    "have changed; see prober.py's module docstring",
                    host, port,
                )
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                TimeoutError, _ProtocolError) as exc:
            logger.warning(
                "Reached %s:%d but version.js request failed (software_version "
                "will be empty): %s", host, port, exc,
            )

    return result
