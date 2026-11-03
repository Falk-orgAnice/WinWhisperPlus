"""Usage statistics persistence and aggregation for recording sessions."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from utils.paths import config_directory


def _statistics_path() -> Path:
    stats_dir = config_directory()
    stats_dir.mkdir(parents=True, exist_ok=True)
    return stats_dir / "statistics.json"


class StatisticsStore:
    """Stores per-session recording metrics and provides period aggregations."""

    def __init__(self, *, path: Path | None = None, persist: bool = True) -> None:
        self._path = path or _statistics_path()
        self._persist = persist
        self._lock = threading.Lock()
        self._sessions: list[dict] = []
        if self._persist:
            self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            sessions = data.get("sessions", [])
            if isinstance(sessions, list):
                self._sessions = [s for s in sessions if isinstance(s, dict)]
        except (json.JSONDecodeError, OSError):
            self._sessions = []

    def save(self) -> None:
        if not self._persist:
            return
        payload = {"sessions": self._sessions}
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def record_session(
        self,
        *,
        started_at: datetime,
        duration_seconds: float,
        language: str | None = None,
    ) -> None:
        duration = max(0.0, float(duration_seconds))
        session = {
            "started_at": started_at.isoformat(timespec="seconds"),
            "duration_seconds": duration,
        }
        if language:
            session["language"] = language

        with self._lock:
            self._sessions.append(session)
            self.save()

    def get_aggregates(self, period: str) -> list[dict]:
        """Return descending period aggregates for day/week/month."""
        if period not in {"day", "week", "month"}:
            raise ValueError("period must be one of: day, week, month")

        buckets: dict[str, dict] = {}
        for session in self._sessions:
            started_at_raw = session.get("started_at")
            duration_raw = session.get("duration_seconds", 0.0)
            if not isinstance(started_at_raw, str):
                continue
            try:
                started_at = datetime.fromisoformat(started_at_raw)
            except ValueError:
                continue
            duration = max(0.0, float(duration_raw))
            key = self._period_key(started_at, period)
            if key not in buckets:
                buckets[key] = {
                    "period": key,
                    "count": 0,
                    "total_seconds": 0.0,
                    "avg_seconds": 0.0,
                }
            buckets[key]["count"] += 1
            buckets[key]["total_seconds"] += duration

        rows = list(buckets.values())
        for row in rows:
            if row["count"] > 0:
                row["avg_seconds"] = row["total_seconds"] / row["count"]

        rows.sort(key=lambda r: r["period"], reverse=True)
        return rows

    def _period_key(self, dt: datetime, period: str) -> str:
        if period == "day":
            return dt.strftime("%Y-%m-%d")
        if period == "week":
            iso_year, iso_week, _ = dt.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        return dt.strftime("%Y-%m")
