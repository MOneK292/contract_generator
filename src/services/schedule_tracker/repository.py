"""SQLite persistence repository for schedule tracking state."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import Generator

_logger = logging.getLogger(__name__)


class ScheduleRepository:
    """Manages persistent schedule state in SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that opens and cleanly closes an SQLite connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema if not exists."""
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_state (
                    manager_name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time_slot TEXT NOT NULL,
                    slot_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (manager_name, date, time_slot)
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_schedule_manager_date
                ON schedule_state (manager_name, date);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitoring_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    poll_interval_seconds INTEGER NOT NULL DEFAULT 60,
                    notification_start_time TEXT NOT NULL DEFAULT '09:00',
                    notification_end_time TEXT NOT NULL DEFAULT '20:00',
                    last_check_time TIMESTAMP,
                    last_success_time TIMESTAMP
                );
                """
            )
            # Insert default row if not exists
            conn.execute(
                """
                INSERT OR IGNORE INTO monitoring_settings (id, enabled) VALUES (1, 1);
                """
            )
            conn.commit()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_monitoring_settings (
                    user_id INTEGER PRIMARY KEY,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    notification_start_time TEXT NOT NULL DEFAULT '09:00',
                    notification_end_time TEXT NOT NULL DEFAULT '20:00',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()
        _logger.debug("Schedule database initialized at %s", self.db_path)

    def _sync_load_schedule(self, manager_name: str, date: str) -> dict[str, str]:
        """Load schedule dictionary for manager and date synchronously."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                SELECT time_slot, slot_value
                FROM schedule_state
                WHERE manager_name = ? AND date = ?
                ORDER BY time_slot;
                """,
                (manager_name, date),
            )
            return {row["time_slot"]: row["slot_value"] for row in cursor.fetchall()}

    def _sync_save_schedule(
        self, manager_name: str, date: str, schedule: dict[str, str]
    ) -> None:
        """Save schedule dictionary for manager and date in a transaction synchronously."""
        with self._connection() as conn:
            conn.execute(
                """
                DELETE FROM schedule_state
                WHERE manager_name = ? AND date = ?;
                """,
                (manager_name, date),
            )
            if schedule:
                conn.executemany(
                    """
                    INSERT INTO schedule_state (manager_name, date, time_slot, slot_value, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP);
                    """,
                    [
                        (manager_name, date, time_slot, slot_value)
                        for time_slot, slot_value in schedule.items()
                    ],
                )
            conn.commit()

    def _sync_cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """Delete records older than specified number of days."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM schedule_state
                WHERE updated_at < datetime('now', ?);
                """,
                (f"-{days_to_keep} days",),
            )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count

    def _sync_get_settings(self) -> dict[str, any]:
        with self._connection() as conn:
            cursor = conn.execute("SELECT * FROM monitoring_settings WHERE id = 1;")
            row = cursor.fetchone()
            return dict(row) if row else {}

    def _sync_get_user_settings(self, user_id: int) -> dict[str, any]:
        with self._connection() as conn:
            cursor = conn.execute("SELECT * FROM user_monitoring_settings WHERE user_id = ?;", (int(user_id),))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                res["enabled"] = bool(res.get("enabled", 1))
                return res
            # Return defaults for uninitialized user
            return {
                "user_id": int(user_id),
                "enabled": True,
                "notification_start_time": "09:00",
                "notification_end_time": "20:00",
            }

    def _sync_update_user_settings(
        self,
        user_id: int,
        enabled: bool | None = None,
        notification_start_time: str | None = None,
        notification_end_time: str | None = None,
    ) -> None:
        user_id_int = int(user_id)
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_monitoring_settings (user_id, enabled, notification_start_time, notification_end_time)
                VALUES (?, 1, '09:00', '20:00');
                """,
                (user_id_int,),
            )
            updates = []
            params = []
            if enabled is not None:
                updates.append("enabled = ?")
                params.append(1 if enabled else 0)
            if notification_start_time is not None:
                updates.append("notification_start_time = ?")
                params.append(notification_start_time)
            if notification_end_time is not None:
                updates.append("notification_end_time = ?")
                params.append(notification_end_time)

            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(user_id_int)
                conn.execute(
                    f"UPDATE user_monitoring_settings SET {', '.join(updates)} WHERE user_id = ?",
                    tuple(params),
                )
            conn.commit()

    def _sync_update_settings(
        self,
        enabled: bool | None = None,
        poll_interval_seconds: int | None = None,
        notification_start_time: str | None = None,
        notification_end_time: str | None = None,
        last_check_time: str | None = None,
        last_success_time: str | None = None,
    ) -> None:
        updates = []
        params = []
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if poll_interval_seconds is not None:
            updates.append("poll_interval_seconds = ?")
            params.append(poll_interval_seconds)
        if notification_start_time is not None:
            updates.append("notification_start_time = ?")
            params.append(notification_start_time)
        if notification_end_time is not None:
            updates.append("notification_end_time = ?")
            params.append(notification_end_time)
        if last_check_time is not None:
            updates.append("last_check_time = ?")
            params.append(last_check_time)
        if last_success_time is not None:
            updates.append("last_success_time = ?")
            params.append(last_success_time)

        if not updates:
            return

        params.append(1)  # for id = 1
        with self._connection() as conn:
            conn.execute(
                f"UPDATE monitoring_settings SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()

    async def get_settings(self) -> dict[str, any]:
        """Get monitoring settings asynchronously."""
        return await asyncio.to_thread(self._sync_get_settings)

    async def update_settings(self, **kwargs) -> None:
        """Update monitoring settings asynchronously."""
        await asyncio.to_thread(self._sync_update_settings, **kwargs)

    async def get_user_settings(self, user_id: int) -> dict[str, any]:
        """Get user monitoring settings asynchronously."""
        return await asyncio.to_thread(self._sync_get_user_settings, user_id)

    async def update_user_settings(self, user_id: int, **kwargs) -> None:
        """Update user monitoring settings asynchronously."""
        await asyncio.to_thread(self._sync_update_user_settings, user_id, **kwargs)

    async def load_schedule(self, manager_name: str, date: str) -> dict[str, str]:
        """Load schedule asynchronously."""
        return await asyncio.to_thread(self._sync_load_schedule, manager_name, date)

    async def save_schedule(
        self, manager_name: str, date: str, schedule: dict[str, str]
    ) -> None:
        """Save schedule asynchronously."""
        await asyncio.to_thread(self._sync_save_schedule, manager_name, date, schedule)

    async def cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """Clean up old records asynchronously."""
        return await asyncio.to_thread(self._sync_cleanup_old_records, days_to_keep)
