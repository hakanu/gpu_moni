"""
Optional Local Energy / Wattage Burn Tracker for GPU Sentry.
Integrates live GPU wattage over time (Wh = Watts * dt / 3600) into lightweight
per-day, per-device buckets stored locally in ~/.gpu_sentry_energy.json.
Computes Today, Last 7 Days, and Last 30 Days energy consumption (kWh) and
optional estimated electricity cost. 100% local — never leaves your machine.
"""

import json
import os
import time
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from core.gpu_types import GpuDevice, GpuMetrics
from core.settings import get_settings


ENERGY_PATH = os.path.join(os.path.expanduser("~"), ".gpu_sentry_energy.json")


class EnergyTracker:
    """Integrates GPU power draw into local daily Wh buckets (pruned after 35 days)."""

    def __init__(self, path: str = ENERGY_PATH):
        self.path = path
        # Schema: {"days": {"YYYY-MM-DD": {"device_id": {"name": str, "wh": float}}}}
        self._days: Dict[str, Dict[str, dict]] = {}
        self._last_ts: Optional[float] = None
        self._last_save_ts: float = 0.0
        self._dirty: bool = False
        self.load()

    def load(self):
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("days"), dict):
                self._days = raw["days"]
                self._prune_old_days()
        except Exception:
            self._days = {}

    def save(self, force: bool = False):
        if not self._dirty and not force:
            return
        try:
            self._prune_old_days()
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"days": self._days}, f, indent=2)
            os.replace(tmp, self.path)
            self._dirty = False
            self._last_save_ts = time.time()
        except Exception:
            pass

    def reset(self):
        self._days.clear()
        self._dirty = True
        self.save(force=True)

    def _prune_old_days(self, keep_days: int = 35):
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        for day_key in list(self._days.keys()):
            if day_key < cutoff:
                self._days.pop(day_key, None)

    def record_sample(self, devices: list[GpuDevice], metrics_by_id: Dict[str, GpuMetrics]):
        """Integrates wattage over elapsed time since previous sample."""
        sd = get_settings().data
        now = time.time()
        if not sd.energy_tracking_enabled:
            self._last_ts = now
            return

        if self._last_ts is None:
            self._last_ts = now
            return

        dt = now - self._last_ts
        self._last_ts = now
        # Ignore huge gaps (e.g. PC sleep/hibernate) so we don't invent phantom energy
        if dt <= 0 or dt > 30.0:
            return

        today_key = date.today().isoformat()
        day_bucket = self._days.setdefault(today_key, {})

        name_map = {d.device_id: d.name for d in devices}
        for dev_id, m in metrics_by_id.items():
            watts = float(m.power_draw_w or 0.0)
            if watts <= 0.1:
                continue
            wh_delta = (watts * dt) / 3600.0
            entry = day_bucket.get(dev_id)
            if entry is None:
                entry = {"name": name_map.get(dev_id, dev_id), "wh": 0.0}
                day_bucket[dev_id] = entry
            elif dev_id in name_map:
                entry["name"] = name_map[dev_id]
            entry["wh"] = round(float(entry.get("wh", 0.0)) + wh_delta, 6)
            self._dirty = True

        if self._dirty and (now - self._last_save_ts) >= 30.0:
            self.save()

    def get_totals_kwh(self) -> Tuple[float, float, float]:
        """Returns (today_kwh, last_7d_kwh, last_30d_kwh) across all tracked GPUs."""
        today = date.today()
        d_today = today.isoformat()
        d_7 = (today - timedelta(days=6)).isoformat()
        d_30 = (today - timedelta(days=29)).isoformat()

        wh_today = 0.0
        wh_7 = 0.0
        wh_30 = 0.0

        for day_key, bucket in self._days.items():
            day_sum = sum(float(v.get("wh", 0.0)) for v in bucket.values() if isinstance(v, dict))
            if day_key == d_today:
                wh_today += day_sum
            if day_key >= d_7:
                wh_7 += day_sum
            if day_key >= d_30:
                wh_30 += day_sum

        return (wh_today / 1000.0, wh_7 / 1000.0, wh_30 / 1000.0)

    def get_per_device_7d_kwh(self) -> Dict[str, Tuple[str, float]]:
        """Returns {device_id: (gpu_name, last_7d_kwh)}."""
        d_7 = (date.today() - timedelta(days=6)).isoformat()
        totals: Dict[str, float] = {}
        names: Dict[str, str] = {}
        for day_key, bucket in self._days.items():
            if day_key < d_7:
                continue
            for dev_id, info in bucket.items():
                if not isinstance(info, dict):
                    continue
                totals[dev_id] = totals.get(dev_id, 0.0) + float(info.get("wh", 0.0))
                if info.get("name"):
                    names[dev_id] = str(info["name"])
        return {k: (names.get(k, k), v / 1000.0) for k, v in totals.items()}
