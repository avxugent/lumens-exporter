"""
Prometheus collector for Lumens VC-TR40/VC-TR40N PTZ auto-tracking cameras.

Probes one or more cameras over their unauthenticated HTTP login page and
version.js asset, and exposes basic reachability plus best-effort device
identity (model, software version) as Prometheus metrics.
"""

from __future__ import annotations

import logging
from typing import Any, Generator

from prometheus_client.core import GaugeMetricFamily, InfoMetricFamily, Metric

from .prober import ProbeResult, probe_device

logger = logging.getLogger(__name__)


class LumensCollector:
    """
    A Prometheus custom collector that probes Lumens VC-TR40/VC-TR40N cameras.

    Each call to :meth:`collect` probes every configured device fresh (no
    caching) and yields the results.
    """

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        """
        :param devices: List of device configuration dicts. Each dict must
            contain at least ``name`` and ``host``; optional keys are
            ``port`` and ``timeout``.
        """
        self._devices = devices

    # ------------------------------------------------------------------
    # prometheus_client collector interface
    # ------------------------------------------------------------------

    def describe(self) -> Generator[Metric, None, None]:
        yield GaugeMetricFamily("probe_success", "")
        yield GaugeMetricFamily("probe_duration_seconds", "")
        yield InfoMetricFamily("lumens_device", "")

    def collect(self) -> Generator[Metric, None, None]:
        """Probe all devices and yield Prometheus metric families."""
        results: list[tuple[dict[str, Any], ProbeResult]] = [
            (dev_cfg, self._probe(dev_cfg)) for dev_cfg in self._devices
        ]
        base_labels = ["device", "host"]

        # --- probe_success / probe_duration_seconds ---
        success_family = GaugeMetricFamily(
            "probe_success",
            "1 if the device's login page responded, 0 otherwise.",
            labels=base_labels,
        )
        duration_family = GaugeMetricFamily(
            "probe_duration_seconds",
            "Duration of the probe in seconds.",
            labels=base_labels,
        )
        for dev_cfg, r in results:
            labels = [dev_cfg["name"], dev_cfg["host"]]
            success_family.add_metric(labels, 1.0 if r.success else 0.0)
            duration_family.add_metric(labels, r.duration_seconds)
        yield success_family
        yield duration_family

        # --- lumens_device (info) ---
        device_family = InfoMetricFamily(
            "lumens_device",
            "Device identity scraped from the camera's unauthenticated login "
            "page and version.js asset (model, software_version). "
            "Best-effort, and 'serial' is never populated without a login "
            "flow this exporter doesn't implement — see prober.py.",
            labels=base_labels,
        )
        for dev_cfg, r in results:
            info: dict[str, str] = {}
            if r.model:
                info["model"] = r.model
            if r.serial:
                info["serial"] = r.serial
            if r.software_version:
                info["software_version"] = r.software_version
            if info:
                device_family.add_metric([dev_cfg["name"], dev_cfg["host"]], info)
        yield device_family

    # ------------------------------------------------------------------
    # Device probing
    # ------------------------------------------------------------------

    def _probe(self, dev_cfg: dict[str, Any]) -> ProbeResult:
        """Probe a single device and return the result."""
        return probe_device(
            host=dev_cfg["host"],
            port=int(dev_cfg.get("port") or 80),
            timeout=float(dev_cfg.get("timeout", 10.0)),
        )
