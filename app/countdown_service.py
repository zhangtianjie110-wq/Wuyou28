"""Countdown state for the YU28 next-draw indicator.

The service owns the clock and converts the latest YU28 record into display
values.  UI pages only consume the emitted text; they do not perform time
arithmetic themselves.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import re

from PySide6.QtCore import QObject, QTimer, Signal


_COUNTDOWN_RE = re.compile(r"^(?P<minutes>\d{1,3}):(?P<seconds>\d{2})$")


class CountdownService(QObject):
    """Maintain a one-second YU28 countdown from an existing draw record."""

    changed = Signal(str, str)

    def __init__(self, parent: QObject | None = None, interval_minutes: int = 5):
        super().__init__(parent)
        self.interval_minutes = max(1, int(interval_minutes))
        self._target: datetime | None = None
        self._expected_time = "—"
        self._seconds_remaining: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    @property
    def seconds_remaining(self) -> int | None:
        return self._seconds_remaining

    @property
    def expected_time(self) -> str:
        return self._expected_time

    def set_draw(self, record: object | None) -> None:
        """Set the latest YU28 record and immediately publish its state."""
        self._target = None
        self._expected_time = "—"
        self._seconds_remaining = None
        if record is not None:
            countdown = self._parse_countdown(getattr(record, "countdown", ""))
            if countdown is not None:
                now = datetime.now().astimezone()
                self._target = now + timedelta(seconds=countdown)
            else:
                self._target = self._fallback_target(getattr(record, "draw_time", ""))
            if self._target is not None:
                self._expected_time = self._target.astimezone().strftime("%H:%M")
                self._update_remaining()
        self._emit()

    def clear(self) -> None:
        self._target = None
        self._expected_time = "—"
        self._seconds_remaining = None
        self._emit()

    def tick(self) -> None:
        """Recompute remaining time without reading data or touching the UI."""
        if self._target is None:
            return
        previous = self._seconds_remaining
        self._update_remaining()
        if self._seconds_remaining != previous:
            self._emit()

    def stop(self) -> None:
        self._timer.stop()

    @staticmethod
    def _parse_countdown(value: object) -> int | None:
        match = _COUNTDOWN_RE.fullmatch(str(value or "").strip())
        if not match:
            return None
        minutes = int(match.group("minutes"))
        seconds = int(match.group("seconds"))
        if seconds > 59:
            return None
        return minutes * 60 + seconds

    def _fallback_target(self, value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            parsed = datetime.fromisoformat(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        target = parsed + timedelta(minutes=self.interval_minutes)
        now = datetime.now(target.tzinfo)
        while target <= now:
            target += timedelta(minutes=self.interval_minutes)
        return target

    def _update_remaining(self) -> None:
        if self._target is None:
            self._seconds_remaining = None
            return
        now = datetime.now(self._target.tzinfo)
        self._seconds_remaining = max(0, int((self._target - now).total_seconds()))

    def _emit(self) -> None:
        if self._seconds_remaining is None:
            text = "等待数据"
        else:
            minutes, seconds = divmod(self._seconds_remaining, 60)
            text = f"{minutes:02d}:{seconds:02d}"
        self.changed.emit(text, self._expected_time)
